import re

path = '/opt/stonk-ai/generate_popup_content.py'
with open(path) as f: c = f.read()

# Remove broken nice_join if present
bad = '''def nice_join(items, sep=, , last_sep= and ):
    Join a list naturally. Oxford comma, clean.'''
if 'def nice_join(' in c and bad in c:
    c = c.replace(bad, '')
    print('Removed broken nice_join')

# Insert clean nice_join at module level
if 'def nice_join(' not in c:
    idx = c.find('\ndef _what_it_is')
    helper = '''def nice_join(items, sep=', ', last_sep=' and '):
    if not items:
        return ''
    *rest, last = items
    if not rest:
        return last
    return sep.join(rest) + last_sep + last

'''
    c = c[:idx] + helper + c[idx:]
    print('Added nice_join')
else:
    print('nice_join already present')

with open(path, 'w') as f:
    f.write(c)
print('Done')
