"""FNV legacy DDS downscaler with normal-aware filtering. Python 3.10+."""
from pathlib import Path
import csv, datetime, io, math, os, queue, shutil, struct, tempfile, threading
import numpy as np
from PIL import Image
from safe_io import roots,scan,reject_links,atomic_write,SafeCSV
Image.MAX_IMAGE_PIXELS=67108864

NORMAL_SUFFIXES = ('_n', '_normal', '_norm', '_nor', '_normalmap')
DATA_SUFFIXES = ('_g', '_m', '_s', '_em', '_mask', '_spec', '_gloss')
MODES = ('Auto (normal-map filename suffix)', 'All are color textures', 'All are normal maps', 'All are linear masks / data')
FORMATS = ('DXT5 (smaller normal maps)', 'RGBA8 (higher-quality normal maps)')

class ReviewError(ValueError): pass

def u32(b,offset): return struct.unpack_from('<I',b,offset)[0]
def put(b,offset,value): struct.pack_into('<I',b,offset,value)
def power2(n): return n>0 and n&(n-1)==0

def header(data):
    if len(data)<128 or data[:4]!=b'DDS ' or u32(data,4)!=124 or u32(data,76)!=32:
        raise ValueError('Invalid DDS header')
    w,h=u32(data,16),u32(data,12); count=u32(data,28) or 1
    if not w or not h or w>8192 or h>8192 or w*h>67108864: raise ValueError('Invalid or excessive DDS dimensions')
    if u32(data,112)&(0x200|0x200000) or u32(data,24)>1:
        raise ReviewError('Cubemap or volume texture: requires a dedicated texture tool')
    flags=u32(data,80); four=data[84:88]
    if flags&4:
        if four not in (b'DXT1',b'DXT3',b'DXT5'):
            raise ReviewError('Unsupported DDS format '+repr(four)+'; no automatic channel reinterpretation')
        fmt=four.decode()
    else:
        if not flags&0x40 or u32(data,88) not in (24,32):
            raise ReviewError('Unsupported uncompressed DDS pixel layout')
        if [u32(data,o) for o in (92,96,100)] not in ([0xff0000,0xff00,0xff],[0xff,0xff00,0xff0000]):
            raise ReviewError('Unusual DDS channel masks')
        if u32(data,88)==32 and u32(data,104) not in (0,0xff000000): raise ReviewError('Unusual alpha mask')
        if u32(data,8)&8 and u32(data,20)!=w*(u32(data,88)//8): raise ReviewError('Padded DDS row pitch is unsupported')
        fmt='RGBA8'
    if not power2(w) or not power2(h): raise ReviewError('Non-power-of-two texture: dimensions need manual review')
    if count>max(w,h).bit_length(): raise ValueError('Invalid mip count')
    return w,h,count,fmt

def level_bytes(w,h,fmt,bits=32):
    if fmt in ('DXT1','DXT3','DXT5'): return max(1,(w+3)//4)*max(1,(h+3)//4)*(8 if fmt=='DXT1' else 16)
    return w*h*(bits//8)

def inspect(data,decode=False):
    w,h,count,fmt=header(data); offset=128; bits=u32(data,88)
    for index in range(count):
        size=level_bytes(w,h,fmt,bits)
        if offset+size>len(data): raise ValueError('Truncated DDS mip '+str(index))
        if decode:
            single=bytearray(data[:128]); put(single,12,h); put(single,16,w); put(single,28,1)
            put(single,8,u32(single,8)&~0x20000); put(single,108,0x1000)
            put(single,20,size if fmt!='RGBA8' else w*(bits//8))
            with Image.open(io.BytesIO(single+data[offset:offset+size])) as im: im.load()
        offset+=size; w=max(1,w//2); h=max(1,h//2)
    return header(data)

def resized_plane(plane,size):
    return np.asarray(Image.fromarray(np.ascontiguousarray(plane,dtype=np.float32)).resize(size,Image.Resampling.BOX),dtype=np.float32)

def resize_rgba(image,size,normal=False,srgb=False):
    # Channels are independent: alpha can be gloss/specularity, not transparency.
    a=np.asarray(image.convert('RGBA'))
    planes=[]
    # Work one source channel at a time to limit memory use on large textures.
    for i in range(3):
        plane=a[:,:,i].astype(np.float32)/255.0
        if normal: plane=plane*2-1
        elif srgb: plane=np.where(plane<=0.04045,plane/12.92,((plane+0.055)/1.055)**2.4)
        planes.append(resized_plane(plane,size))
    rgb=np.stack(planes,axis=2)
    if normal:
        length=np.linalg.norm(rgb,axis=2,keepdims=True); zero=length[:,:,0]<1e-6
        rgb=rgb/np.maximum(length,1e-8); rgb[zero]=[0,0,1]
        rgb=(rgb+1)*0.5
    elif srgb: rgb=np.where(rgb<=0.0031308,rgb*12.92,1.055*np.maximum(rgb,0)**(1/2.4)-0.055)
    alpha=resized_plane(a[:,:,3].astype(np.float32)/255.0,size)
    result=np.concatenate([rgb,alpha[:,:,None]],axis=2)
    return Image.fromarray(np.rint(np.clip(result,0,1)*255).astype(np.uint8))

def target_size(w,h,maximum):
    while max(w,h)>maximum: w=max(1,w//2); h=max(1,h//2)
    return w,h

def encode_level(im,fmt):
    stream=io.BytesIO()
    if fmt=='RGBA8': im.convert('RGBA').save(stream,format='DDS')
    else: im.convert('RGBA').save(stream,format='DDS',pixel_format=fmt)
    return stream.getvalue()

def build_dds(image,size,normal,fmt,srgb=False,mips=True):
    current=resize_rgba(image,size,normal,srgb) if image.size!=size or normal else image.convert('RGBA')
    first=None; payload=[]; count=0
    while True:
        encoded=encode_level(current,fmt)
        if first is None: first=bytearray(encoded[:128])
        block=encoded[128:]; expected=level_bytes(*current.size,fmt)
        if len(block)!=expected: raise ValueError('Encoder returned an unexpected DDS payload length')
        payload.append(block); count+=1
        if not mips or current.size==(1,1): break
        current=resize_rgba(current,(max(1,current.width//2),max(1,current.height//2)),normal,srgb)
    put(first,28,count); put(first,108,0x1000|(0x400008 if count>1 else 0))
    put(first,8,(u32(first,8)|0x20000) if count>1 else (u32(first,8)&~0x20000))
    put(first,20,level_bytes(*size,fmt) if fmt!='RGBA8' else size[0]*4)
    if fmt!='RGBA8': put(first,88,0) # compressed pixel formats use FourCC, not RGB bit count
    result=bytes(first)+b''.join(payload)
    w,h,n,actual=inspect(result,decode=True)
    if (w,h)!=size or actual!=fmt or n!=count: raise ValueError('Output verification failed')
    if result[84:88]==b'DX10': raise ValueError('DX10 output is not allowed')
    return result,count

def write_exclusive(path,data):
    atomic_write(path,data=data)


def classify(path,mode):
    stem=path.stem.lower()
    if mode==MODES[2]: return 'normal'
    if mode==MODES[3]: return 'data'
    if mode==MODES[1]: return 'color'
    if stem.endswith(NORMAL_SUFFIXES): return 'normal'
    if stem.endswith(DATA_SUFFIXES): return 'data'
    return 'color'

def process(src,dest,maximum,normal_max,mode,normal_format,srgb,mips):
    reject_links(src); reject_links(dest)
    if src.stat().st_size>384*1024**2: raise ValueError('DDS exceeds the 384 MiB input limit')
    with src.open('rb') as check:
        prefix=check.read(128)
    if len(prefix)<128: raise ValueError('Truncated DDS header')
    if u32(prefix,12)*u32(prefix,16)>67108864: raise ValueError('DDS exceeds 64 megapixel memory limit')
    raw=src.read_bytes()
    try: w,h,count,fmt=inspect(raw)
    except ReviewError as exc:
        return 'review','','','','Not output; original retained for review: '+str(exc)
    kind=classify(src,mode); size=target_size(w,h,normal_max if kind=='normal' else maximum)
    # Leave in-limit files bit-identical, including existing mipmaps and compression.
    if size==(w,h):
        with Image.open(io.BytesIO(raw)) as im: im.load()
        write_exclusive(dest,raw)
        return 'copied',f'{w}x{h}',f'{w}x{h}',count,'Already within limit; copied byte-for-byte'
    with Image.open(io.BytesIO(raw)) as im: image=im.convert('RGBA')
    if kind=='normal': output_format='RGBA8' if normal_format==FORMATS[1] else 'DXT5'
    else:
        output_format=fmt
        if fmt=='DXT1' and image.getchannel('A').getextrema()[0]<255: output_format='DXT5'
    blob,mipcount=build_dds(image,size,kind=='normal',output_format,srgb and kind=='color',mips)
    write_exclusive(dest,blob)
    return 'resized',f'{w}x{h}',f'{size[0]}x{size[1]}',mipcount,f'{kind}; {output_format}; verified all mip levels'

def batch(source,output,maximum=1024,normal_max=1024,mode=MODES[0],normal_format=FORMATS[0],srgb=False,mips=True,recursive=True,stop=None,emit=lambda *a:None):
    source,output=roots(source,output)
    if maximum not in (128,256,512,1024,2048,4096,8192) or normal_max not in (128,256,512,1024,2048,4096,8192): raise ValueError('Invalid size preset')
    if mode not in MODES or normal_format not in FORMATS: raise ValueError('Invalid processing mode')
    files=scan(source,'.dds',recursive,stop)
    if not files: raise ValueError('No DDS files found')
    seen=set()
    for p in files:
        if p.is_symlink() or source not in p.resolve().parents: raise ValueError('Linked input outside selected source: '+str(p))
        key=str(p.relative_to(source)).casefold()
        if key in seen: raise ValueError('Case-insensitive duplicate filename: '+key)
        seen.add(key)
    output.mkdir(parents=True,exist_ok=True)
    report=output/('texture-report-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')+'.csv')
    counts={k:0 for k in ('resized','copied','review','skipped','failed')}; before=after=0; cancelled=False
    emit('total',len(files))
    with report.open('w',encoding='utf-8-sig',newline='') as f:
        writer=SafeCSV(f); writer.writerow(['File','Status','Original size','Output size','Mip levels','Original bytes','Output bytes','Details'])
        for index,src in enumerate(files,1):
            if stop is not None and stop.is_set(): cancelled=True; break
            rel=src.relative_to(source); dest=output/rel
            if output not in dest.resolve().parents: raise ValueError('Output contains a link outside selected destination')
            old=new=n=''; b=src.stat().st_size; a=0
            emit('current',str(rel))
            try:
                reject_links(src); reject_links(dest)
                if dest.exists(): status='skipped'; details='Existing output kept; not revalidated'
                else:
                    status,old,new,n,details=process(src,dest,maximum,normal_max,mode,normal_format,srgb,mips)
                    if status!='review': a=dest.stat().st_size; before+=b; after+=a
            except Exception as exc: status='failed'; details=str(exc)
            counts[status]+=1
            writer.writerow([str(rel),status,old,new,n,b,a,details]); f.flush()
            emit('log',f'{status.upper()}: {rel} | {old} -> {new} | {details}'); emit('progress',index)
    result={'counts':counts,'cancelled':cancelled,'report':str(report),'before':before,'after':after}
    emit('done',result); return result
