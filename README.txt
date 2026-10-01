FNV TEXTURE DOWNSCALER 1.0 - WINDOWS 10/11 x64

1. Extract the entire ZIP into a local folder you control.
2. Double-click FNV Texture Downscaler.exe. Python and image libraries are included.
3. Choose the DDS input folder and a separate output folder.
4. Set texture and normal-map limits (1024 pixels on the longest edge by default).
5. Click Preview batch, then Downscale textures.
6. Open output or View report when finished.

Keep app and runtime beside the EXE. This is a portable folder application, not a single
self-contained EXE. No installation, pip, network connection or administrator rights are
needed. Source files and existing outputs are never overwritten or deleted.

FNV output uses legacy DDS: DXT1, DXT3, DXT5 or uncompressed RGBA8. Aspect ratio is retained;
4096x2048 becomes 1024x512 at a 1024 cap. Textures within the cap are copied unchanged.
Mipmaps are regenerated only on resized textures; their complete chain reaches 1x1.
Advanced settings let you disable mip generation, select RGBA8 normal output, or enable
sRGB filtering for known color textures. Normals/data always use linear filtering.

Auto recognizes _n, _normal, _norm, _nor and _normalmap as normals. Use All are normal maps
for a folder with nonstandard names. Only conventional RGB XYZ normals are supported;
packed DXT5nm/BC5 maps need a different tool. RGB direction vectors are filtered and
renormalized; alpha is independently filtered. No green-channel flip is applied.
DXT5 normals save space; RGBA8 avoids block-compression artifacts but can be larger.

Unsupported formats, cubemaps, volumes and non-power-of-two dimensions are marked REVIEW
and left in the input folder. They are NOT copied into output in this version. Invalid
or truncated DDS files are FAILED. Review the report so you know what is missing.
Only DDS files are processed; output is not a complete copy of your mod.
Input cap: 8192 pixels per edge, 64 million pixels, 384 MiB per DDS. Larger images need
another tool. UI/font atlases and cutout textures should be inspected after resizing.

If you select Data\Textures as input, output contents belong inside Data\Textures. If you
select a parent containing Textures, that extra folder level is retained.
Stop completes the current texture. Choose a new output folder to rerun with new settings.

Read AUDIT.txt for review findings and TEST-RESULTS.txt for what was actually tested.
This application is not digitally signed; do not disable Windows security software.
If blocked or an error appears, send the exact message and small generated report.
The executable's SHA-256 is supplied in SHA256SUMS.txt for integrity checking.
The source code is in app; native launcher/build source is in source.
