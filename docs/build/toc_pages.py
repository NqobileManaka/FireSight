import json, subprocess, re, sys
pdf=sys.argv[1]; heads=json.load(open('headings.json'))
n=int(re.search(r'Pages:\s+(\d+)',subprocess.run(['pdfinfo',pdf],capture_output=True,text=True).stdout).group(1))
txt=[subprocess.run(['pdftotext','-f',str(i),'-l',str(i),'-layout',pdf,'-'],capture_output=True,text=True).stdout for i in range(1,n+1)]
out={}
for h in heads:
    key=re.sub(r'\s+',' ',h)
    for i,t in enumerate(txt,1):
        if i<3: continue
        if key in re.sub(r'\s+',' ',t): out[h]=i; break
    else: print("NOT FOUND",h)
json.dump(out,open('toc.json','w'),indent=1); print(len(out),"of",len(heads))
