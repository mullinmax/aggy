ARG BASE_IMAGE=blinder-shared:latest
FROM $BASE_IMAGE as base

COPY . .

RUN pip install -r requirements.txt

CMD ["python", "./app.py"]