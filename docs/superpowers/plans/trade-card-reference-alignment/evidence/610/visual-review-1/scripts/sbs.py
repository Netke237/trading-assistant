import sys
from PIL import Image, ImageDraw, ImageFont
def load(spec):
    f,box=spec.split('@') if '@' in spec else (spec,None)
    im=Image.open(f).convert('RGB')
    if box: im=im.crop(tuple(int(v) for v in box.split(',')))
    return im
out=sys.argv[1]; a=load(sys.argv[2]); b=load(sys.argv[3])
la=sys.argv[4] if len(sys.argv)>4 else 'REFERENCE'; lb=sys.argv[5] if len(sys.argv)>5 else 'CURRENT APP'
try: font=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',22)
except: font=ImageFont.load_default()
H=max(a.height,b.height)+44; W=a.width+b.width+30
c=Image.new('RGB',(W,H),(255,255,255)); d=ImageDraw.Draw(c)
d.text((8,10),la,fill=(0,0,0),font=font); d.text((a.width+38,10),lb,fill=(180,0,0),font=font)
c.paste(a,(0,44)); c.paste(b,(a.width+30,44)); c.save(out); print(out,c.size)
