# Pocketful (stage 1)

Build and start (listens on port 8080 by default; override with `-e PORT=...`):

```sh
docker build -t pocketful-stage1 . && docker run --rm -p 8080:8080 -e PORT=8080 pocketful-stage1
```

Then `curl localhost:8080/health`.
