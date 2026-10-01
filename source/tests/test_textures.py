import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'app'))
from pathlib import Path
import hashlib, io, struct, tempfile, threading
import numpy as np
from PIL import Image
import downscaler as d

def hashfile(p): return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    # Varied normal directions + independent gloss alpha: filtered result must have unit normals.
    a=np.zeros((64,128,4),dtype=np.uint8)
    a[:,:64,:3]=(204,128,230); a[:,64:,:3]=(51,128,230)
    a[:,:,3]=np.linspace(0,255,128).astype(np.uint8)[None,:]
    resized=d.resize_rgba(Image.fromarray(a),(16,8),normal=True)
    v=np.asarray(resized)[:,:,:3]/255*2-1
    assert np.max(np.abs(np.linalg.norm(v,axis=2)-1))<0.012
    assert np.asarray(resized)[:,:,3].min()<20 and np.asarray(resized)[:,:,3].max()>235
    alpha=np.asarray(resized)[:,:,3]
    assert np.max(np.abs(alpha.astype(float)-np.asarray(Image.fromarray(a[:,:,3]).resize((16,8),Image.Resampling.BOX))))<=1
    with tempfile.TemporaryDirectory() as temporary:
        root=Path(temporary); source=root/'source'; source.mkdir(); (source/'nested').mkdir()
        yy,xx=np.mgrid[:256,:512]
        color=np.stack([xx%256,yy%256,(xx+yy)%256,np.full_like(xx,255)],axis=2).astype(np.uint8)
        norm=np.zeros((256,512,4),dtype=np.uint8); norm[:,:,:3]=(128,128,255); norm[:,:,3]=(xx%256).astype(np.uint8)
        for fmt in ('DXT1','DXT3','DXT5','RGBA8'):
            raw,n=d.build_dds(Image.fromarray(color),(512,256),False,fmt)
            assert n==10
            (source/('color_'+fmt+'.dds')).write_bytes(raw)
        (source/'nested'/'test_n.dds').write_bytes(d.build_dds(Image.fromarray(norm),(512,256),True,'DXT5')[0])
        small=source/'small.dds'; small.write_bytes(d.build_dds(Image.new('RGBA',(32,16),(10,20,30,255)),(32,16),False,'DXT1')[0])
        # DDS header with cubemap flag: must stay unchanged and get a review result.
        cube=bytearray(small.read_bytes()); d.put(cube,112,0x200); (source/'cube.dds').write_bytes(cube)
        (source/'bad.dds').write_bytes(b'bad DDS')
        hashes={p:hashfile(p) for p in source.rglob('*.dds')}
        result=d.batch(source,root/'out',maximum=128,normal_max=128)
        assert result['counts']=={'resized':5,'copied':1,'review':1,'skipped':0,'failed':1},result
        for p in (root/'out').rglob('*.dds'):
            if p.name=='cube.dds': continue
            info=d.inspect(p.read_bytes(),decode=True)
            assert max(info[:2])<=128
            if p.name!='small.dds': assert info[2]==8
        assert (root/'out'/'small.dds').read_bytes()==small.read_bytes()
        assert not (root/'out'/'cube.dds').exists()
        for p,v in hashes.items(): assert hashfile(p)==v
        rerun=d.batch(source,root/'out',maximum=128,normal_max=128)
        assert rerun['counts']['skipped']==6
        out2=root/'normalHQ'
        hq=d.batch(source,out2,maximum=128,normal_max=128,normal_format=d.FORMATS[1])
        assert d.header((out2/'nested'/'test_n.dds').read_bytes())[3]=='RGBA8'
        assert d.target_size(4096,2048,1024)==(1024,512)
        assert d.target_size(512,256,1024)==(512,256)
        event=threading.Event(); event.set()
        try: d.batch(source,root/'stopped',stop=event)
        except d.scan.__globals__['Cancelled']: pass
        else: raise AssertionError('Cancelled scan continued')
        try: d.batch(source,source/'bad-destination')
        except ValueError: pass
        else: raise AssertionError('Nested output allowed')
        # DDS single mip and tiny blocks decode, including 1x1 bottom mip.
        raw,n=d.build_dds(Image.new('RGBA',(8,8),(128,128,255,0)),(4,4),True,'DXT5',mips=False)
        assert d.inspect(raw,True)==(4,4,1,'DXT5')
    print('PASS: DXT1/DXT3/DXT5/RGBA8; rectangular aspect ratio; full mipchains through 1x1; normal renormalization; separate alpha filtering; HQ normals; small-file preservation; cubemap review; malformed input handling; originals unchanged; existing output skip; cancellation; nested-output guard.')

if __name__=='__main__': main()
