"""Exact-card comment tools shared by the Daily Run and Snapshot drawers."""


class SharedCommentApi:
    def _comment_backend(self):
        return self._aw() if hasattr(self, '_aw') else self

    def comment_destinations(self, client):
        return self._comment_backend().crm_division_trello_cards(client)

    def job_comment_members(self, card_id):
        from job_comment_mentions import members
        return members(card_id)

    def oneloss_comment_members(self, card_id):
        from personal_notifications import mention_members
        return mention_members(card_id)

    def job_comment_reactions(self, card_id, action_id, code=None, active=None):
        from job_comment_reactions import reactions
        return reactions(card_id, action_id, code, active)

    def drawer_comments(self, client, card_id, refresh=False):
        if not card_id:
            return {'ok': False, 'error': 'Choose a linked card first.'}
        backend = self._comment_backend()
        if refresh:
            cache = getattr(backend, '_comments_cache', {})
            cache.pop(card_id, None)
        return backend.get_card_comments(client, 200, card_id=card_id)

    def drawer_post(self, client, card_id, text):
        if not card_id:
            return {'ok': False, 'error': 'Choose a linked card first.'}
        return self._comment_backend().post_comment(client, text, card_id=card_id)

    def drawer_image(self, client, card_id, attachment_id, big=False):
        if not card_id:
            return {'ok': False, 'error': 'Choose a linked card first.'}
        return self._comment_backend().comment_image(client, attachment_id, big, card_id=card_id)
