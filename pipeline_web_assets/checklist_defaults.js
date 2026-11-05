/* Reviewed EMS residential defaults. Display only: never creates Trello items. */
window.EMS_CHECKLIST_DEFAULTS = [{"name":"INTAKE","items":["RUN","WORKCENTER","ONE DRIVE","TRELLO","COMPANYCAM"]},{"name":"FIELD","items":["INITIAL PAPERWORK","INITIAL PHOTOS","DEMO PHOTOS","DEMO DOCUSKETCH","SCOPE - INITIAL","SCOPE - FINAL","INITIAL DOCUSKETCH","EQUIPMENT COUNT - INITIAL","EQUIPMENT COUNT - FINAL","FINAL PAPERWORK","FINAL PHOTOS","FINAL DOCUSKETCH"]},{"name":"EQUIPMENT COUNT - FIELD","items":[]},{"name":"INITIAL - ADMIN","items":["ATP","CIF","CER","STATE FARM ATR","INITIAL PHOTOS/PHOTO REPORT","INITIAL UPLOAD"]},{"name":"INITIAL - COORDINATOR","items":["DOCUSKETCH LINK","VIDEO LINK","FIELD INITIAL INSPECTION NOTE","INITIAL ADJUSTER UPDATE"]},{"name":"CONTENTS - COORDINATOR","items":["POD","VAULTS","ONSITE","STORAGE UNIT"]},{"name":"IN PROGRESS - ADMIN","items":["ORDER DOCUSKETCH","DEMO PHOTOS","ADDITIONAL DEMO - AFTER DRYING PHOTOS","AFTER DEMO SKTECH","INITIAL SCOPE"]},{"name":"SUBS","items":[]},{"name":"CLOSE OUT - ADMIN","items":["COS","FINAL PHOTOS","FINAL SKETCH","FINAL SCOPE","FINAL EQ COUNT","SNAPSHOT","STATE FARM ATP"]},{"name":"EMS - ESTIMATING","items":["ASSIGNED","BILLED","INVOICED","UPLOADED","EMAILED TO ADJUSTER OR PAYING PARTY "]},{"name":"CONTENTS - ESTIMATING","items":["** PACK OUT **","BILLED","INVOICED","UPLOADED","EMAILED TO ADJUSTER OR PAYING PARTY","** PACK BACK **","BILLED","INVOICED","UPLOADED","EMAILED TO ADJUSTER OR PAYING PARTY"]}];
window.checklistDisplayLists = function(data, division) {
  const lists = data.checklists || [];
  if (lists.length || !data.deferred_loading || String(division).toUpperCase() !== 'EMS') return lists;
  return window.EMS_CHECKLIST_DEFAULTS.map((list, index) => ({
    id: 'default-' + index, name: list.name, pending: true,
    items: list.items.map((name, item) => ({id: 'default-' + index + '-' + item, name, complete: false, pending: true}))
  }));
};
