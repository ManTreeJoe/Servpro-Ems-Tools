"""Bundled reaction choices: no remote catalogue request."""
GROUPS = {
 'Smileys': [('😀','grinning happy'),('😄','smile happy'),('😁','grin'),('😂','laugh tears joy'),('🤣','rolling laugh'),('😊','blush smile'),('😍','heart eyes love'),('😘','kiss'),('😎','cool sunglasses'),('🤔','thinking'),('😐','neutral'),('😢','cry sad'),('😭','sob'),('😮','surprised'),('😬','grimace'),('🙄','eye roll'),('😴','sleep'),('🥳','party'),('😅','sweat smile')],
 'People': [('👍','thumbs up approve'),('👎','thumbs down'),('👏','clap'),('🙌','raised hands'),('🙏','thanks pray'),('👋','wave hello'),('👌','okay'),('✌️','peace victory'),('💪','strong muscle'),('🤞','fingers crossed'),('👀','eyes look'),('🤝','handshake')],
 'Nature': [('🐶','dog'),('🐱','cat'),('🐐','goat'),('🌳','tree'),('🌱','seedling'),('🌻','flower'),('☀️','sun'),('🌧️','rain'),('🔥','fire'),('💧','water drop')],
 'Food': [('☕','coffee'),('🍕','pizza'),('🍔','burger'),('🍩','donut'),('🎂','cake'),('🍎','apple'),('🍿','popcorn')],
 'Work & travel': [('🏠','house home'),('🏢','office building'),('🚗','car'),('🚚','truck'),('✈️','airplane'),('🛠️','tools repair'),('🔨','hammer'),('📷','camera photo'),('📋','clipboard'),('📁','folder'),('📅','calendar'),('💡','idea light bulb'),('🔑','key'),('🏆','trophy'),('🎉','celebrate party'),('🚀','rocket')],
 'Symbols': [('❤️','heart love'),('💚','green heart'),('💙','blue heart'),('💯','hundred perfect'),('✅','check done'),('❌','cross no'),('⚠️','warning'),('❓','question'),('❗','exclamation'),('⭐','star'),('✨','sparkles'),('🔴','red circle'),('🟢','green circle'),('🏁','finish flag')],
}
CHOICES = [{'code':'-'.join(f'{ord(c):04X}' for c in emoji), 'emoji':emoji, 'name':name, 'category':group}
           for group, entries in GROUPS.items() for emoji, name in entries]
CODES = frozenset(row['code'] for row in CHOICES)
