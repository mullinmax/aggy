ARG BASE_IMAGE=blinder-shared:latest
FROM $BASE_IMAGE as base

COPY . .

RUN pip install -r requirements.txt

EXPOSE 5000

CMD ["python", "app.py"]
