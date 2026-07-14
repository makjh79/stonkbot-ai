with open('/opt/stonk-ai/generate_popup_content.py') as f: c=f.read()

bad_block = """    if not items: return 
    *rest, last = items
    if not rest: return last
    return sep.join(rest) + last_sep + last

"""

if bad_block in c:
    c = c.replace(bad_block, '\n')
    with open('/opt/stonk-ai/generate_popup_content.py','w') as f: f.write(c)
    print('Fixed broken block inside _infer_pead')
else:
    print('Block not found')
