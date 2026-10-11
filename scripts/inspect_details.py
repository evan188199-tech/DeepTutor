import json, subprocess
def flat(lang, ref='HEAD'):
    raw=subprocess.run(['git','show',f'{ref}:web/locales/{lang}/app.json'],capture_output=True,text=True,cwd='.').stdout
    return json.loads(raw)
en=flat('en'); pl=flat('pl'); uk=flat('uk'); zh=flat('zh'); fr=flat('fr'); de=flat('de')
plx=[k for k in pl if k not in en]
print("pl extras all plural-suffixed:", all(k.endswith(('_few','_many','_other','_one')) for k in plx))
for k in plx[:3]:
    stem=k.rsplit('_',1)[0]
    enrel=[e for e in en if e.startswith(stem)][:4]
    print(" stem:", stem, "| en relatives:", enrel)
raw13=json.loads(subprocess.run(['git','show','v1.6.13:web/locales/en/app.json'],capture_output=True,text=True,cwd='.').stdout)
for k in en:
    if k in raw13 and raw13[k]!=en[k]:
        print("changed en key:", repr(k), "\n  v1.6.13:", raw13[k][:100], "\n  v1.6.14:", en[k][:100])
print("fr imagegen:", repr(fr.get('settings.providerServices.filter.imagegen')))
print("en imagegen:", repr(en.get('settings.providerServices.filter.imagegen')))
print("de videogen:", repr(de.get('settings.providerServices.filter.videogen')))
print("en videogen:", repr(en.get('settings.providerServices.filter.videogen')))
print("zh 's':", repr(zh.get('s')), "| v1.6.13 en has 's'? ", 's' in raw13, "| fr has 's'? ", 's' in fr, "| en has 's'? ", 's' in en)
r=subprocess.run(['git','log','--format=%h %s','-S','"s": ""','--','web/locales/zh/app.json'],capture_output=True,text=True,cwd='.').stdout
print("zh 's' history:", r.strip().splitlines()[:3])
miss63=json.load(open('evidence/verify-web-locale-parity-20261011/missing-keys-by-language.json'))['fr']['missing_in_window_keys']
print("of fr's 63 window-missing, present in zh:", sum(1 for k in miss63 if k in zh), "in de:", sum(1 for k in miss63 if k in de))
# fr extras: how many end with plural suffixes
frx=[k for k in fr if k not in en]
print("fr extras plural-suffixed:", sum(1 for k in frx if k.endswith(('_few','_many','_one','_other'))), "of", len(frx))
