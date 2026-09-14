/* Compatibility boundary: separate visit fields in the UI, Run lines at export. */
(function (host) {
  const clean = value => String(value || '').trim().replace(/\s+/g, ' ');
  function parse(text, dated = false) {
    const parts = String(text || '').split('|').map(clean);
    const location = parts[1] || '';
    const phone = location.match(/^(.*?)\s+—\s+([+()\d][\d()\s.+-]*(?:\s*(?:ext\.?|x)\s*\d+)?)$/i);
    const phoneOnly = location.startsWith('— ');
    return {job:parts[0] || '', address:phone ? phone[1] : phoneOnly ? '' : location,
      phone:phone ? phone[2] : phoneOnly ? location.slice(2) : '', task:parts[2] || '', date:dated ? parts[3] || '' : '',
      time:parts[dated ? 4 : 3] || '', crew:parts[dated ? 5 : 4] || '',
      status:parts.slice(dated ? 6 : 5).join(' | ')};
  }
  function format(fields, dated = false) {
    const values = Object.values(fields).map(clean);
    if (!values.some(Boolean)) return '';
    const location = clean(fields.phone) ? `${clean(fields.address)} — ${clean(fields.phone)}`.trim() : clean(fields.address);
    const parts = [clean(fields.job), location, clean(fields.task)];
    if (dated) parts.push(clean(fields.date));
    parts.push(clean(fields.time), clean(fields.crew), clean(fields.status));
    // Keep interior blanks: filtering them moves arrival/crew into other columns.
    while (parts.length && !parts[parts.length - 1]) parts.pop();
    return parts.join(' | ');
  }
  host.ScheduleFields = {parse, format};
  if (typeof module !== 'undefined') module.exports = host.ScheduleFields;
})(typeof window === 'undefined' ? globalThis : window);
