# wikicommonsbot
my bot for wikimeda commons. 


# run

```
docker build --tag mycbot:2024.03 .
docker run --rm -v "${PWD}:/opt/commonsbot" -it mycbot:2024.03
chmod 600 user-config.py
```