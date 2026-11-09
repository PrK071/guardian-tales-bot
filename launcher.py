import json, sys, urllib.request, webbrowser
URL='http://127.0.0.1:8765'
try:
    status=json.load(urllib.request.urlopen(URL+'/status',timeout=2))
except Exception:
    import bot
    bot.main()
else:
    if 'coverage' not in status:
        raise SystemExit('Porta 8765 ocupada por outro aplicativo.')
    webbrowser.open(URL)
