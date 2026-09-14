const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const source=fs.readFileSync('home_web_assets/app.js','utf8');
const start=source.indexOf('function navigate('),end=source.indexOf('\nfunction findItem(',start);
let view='dispatch',loads=0;
const classes={toggle(){},add(){},remove(){}};
const frame={getAttribute:()=>'/operations_web_assets/index.html?embedded=1',classList:classes,
 contentWindow:{showView(v){view=v;}},set src(v){loads++;}};
const context={URLSearchParams,MAX_WARM_PANELS:4,findItem:()=>({key:'operations',src:'operations_web_assets/index.html'}),
 state:{frames:new Map([['operations',frame]]),frameOrder:['operations']},
 $:()=>({classList:classes}),$$:()=>[],pywebview:{api:{set_last_panel(){}}}};
vm.createContext(context);vm.runInContext(source.slice(start,end),context);
context.navigate('operations');
assert.equal(view,'home','Operations sidebar must return from the hidden Dispatch subview');
assert.equal(loads,0,'Returning must retain the loaded data, not reload the iframe');
console.log('Operations return navigation passed without reloading data.');
