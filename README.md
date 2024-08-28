# Converj Reason-Based Surveys

When opinions conflict, voting alone does not bring opinions closer together. Competitive voting can even increase partisanship. But reason-based voting helps people to know more, to learn about themselves and each other, and to find more common ground than we expect.

These survey tools have been designed to make it fast & easy for people to express their reasons, and to comprehend others' reasons. 

This repository implements a Dockerized instance of Converj, which you can run inside your private network, to keep sensitive data under your control.

To run:
* Install Docker (Example: https://docs.docker.com/get-started/get-docker)
* Checkout this repository
* Customize `databasePassword*.txt` (Later also customize `webserver/secrets.py`)
* In the checkout directory, run `docker-compose up`
* View the website at http://localhost:5000

Converj is also available as a free cloud service at https://converj.us
