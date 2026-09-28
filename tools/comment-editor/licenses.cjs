// Regenerate bundled dependency notices alongside the editor build.
const fs=require('node:fs'),path=require('node:path');
const root=path.join(__dirname,'node_modules');
const packages=fs.readdirSync(root).filter(name=>!name.startsWith('.')).flatMap(name=>name.startsWith('@')?fs.readdirSync(path.join(root,name)).map(child=>path.join(root,name,child)):[path.join(root,name)]);
const notices=[];
for(const dir of packages){
 const manifest=path.join(dir,'package.json');if(!fs.existsSync(manifest))continue;
 const pkg=JSON.parse(fs.readFileSync(manifest,'utf8'));
 const license=fs.readdirSync(dir).find(name=>/^licen[cs]e(?:\..*)?$/i.test(name));
 if(license)notices.push(`${pkg.name} ${pkg.version}\n${fs.readFileSync(path.join(dir,license),'utf8')}`);
}
fs.writeFileSync(path.join(__dirname,'../../web_shared/vendor/comment-editor.LICENSE.txt'),notices.join('\n\n--------------------\n\n'));
