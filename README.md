# Converj Reason-Based Surveys

When opinions conflict, polling alone does not bring opinions closer together.  Competitive voting can even increase partisanship.  But reason-based voting helps people to know more, to learn about themselves and each other, and to find more common ground than we expect.  Converj surveys make it fast & easy for people to express their reasons, and to comprehend others' reasons. 

This repository implements a Dockerized instance of [Converj](https://github.com/converj/reasonSurvey), which you can run inside your private network, to keep sensitive data under your control.  Converj is also available as a free cloud service at https://converj.net

### To run
* Install [Docker](https://docs.docker.com/get-started/get-docker)
* Git clone this repository
* In the checkout directory:
  * Customize `databasePassword*.txt`
  * Run `docker-compose up`
* View the website at http://localhost:5000

### Do this later
Before sharing surveys with other people:
* Customize `webserver/secrets.py` (will reset user identities)

