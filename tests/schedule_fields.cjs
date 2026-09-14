const assert = require('node:assert/strict');
const {parse,format} = require('../run_doc_editor_web_assets/schedule_fields.js');
for (const dated of [false,true]) {
  for (const missing of ['address','task','time','crew','date','status']) {
    const fields = {job:'Test job',address:'100 Main St',phone:'(555) 555-1234',task:'Monitor',date:dated?'9/18':'',time:'12–3 PM',crew:'Sam, Alex',status:'Call first'};
    fields[missing] = '';
    assert.deepEqual(parse(format(fields,dated),dated),fields,`${dated}:${missing}`);
  }
}
assert.equal(format({job:''}), '');
assert.equal(parse('Legacy free text').job,'Legacy free text');
assert.equal(parse('Job | Address | Task | 9/18 | 12–3 PM | Alex | Call first',true).date,'9/18');
assert.equal(parse('Job | Address | Task | 12–3 PM | Alex | Call | first').status,'Call | first');
console.log('PASS: dated and undated fields, blank columns, phone, legacy text, multi-part notes');
