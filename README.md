# wikicommonsbot
my bot for wikimeda commons. 


# run

```
docker build --tag mycbot:2024.03 .
docker run --rm -v "${PWD}:/opt/commonsbot" -it mycbot:2024.03
chmod 600 user-config.py
```

# near-border cases

When all metro in Moscow except special station: 
```
python3 set-taken-on.py --location "Moscow Oblast" --category 'Category:Kotelniki (Moscow Metro)'
python3 set-taken-on.py --location "Moscow" --category 'Stations of Tagansko-Krasnopresnenskaya Line' --levels 2 --skip-location 'Moscow Oblast'
```