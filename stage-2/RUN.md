# Pocketful (stage 2)

Build and start (listens on port 8080 by default; override with `-e PORT=...`):

```sh
docker build -t pocketful-stage2 . && docker run --rm -p 8080:8080 -e PORT=8080 pocketful-stage2
```

Then `curl localhost:8080/health`.
