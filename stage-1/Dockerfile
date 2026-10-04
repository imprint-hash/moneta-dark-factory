# Standard library only: nothing to install at build or run time.
FROM python:3.12-alpine
WORKDIR /app
COPY app.py ./
ENV PORT=8080 PYTHONUNBUFFERED=1
EXPOSE 8080
CMD ["python", "-u", "app.py"]
