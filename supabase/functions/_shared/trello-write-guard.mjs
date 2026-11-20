/** Same default-off policy as the desktop transport; no saved-token opt-in. */
export function guardedTrelloFetch(fetcher, env) {
  return (url, init = {}) => {
    const method = String(init.method || (url instanceof Request ? url.method : 'GET')).toUpperCase();
    if (!['GET', 'HEAD'].includes(method) &&
        (!['POST', 'PUT', 'PATCH', 'DELETE'].includes(method) ||
         env.ONELOSS_TRELLO_WRITES_ENABLED !== 'true')) {
      throw new Error('trello_writes_disabled');
    }
    return fetcher(url, init);
  };
}
