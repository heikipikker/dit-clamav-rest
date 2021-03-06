import os
import logging
import sys
import timeit

from flask import Flask, request, g
from flask_httpauth import HTTPBasicAuth

import clamd
from passlib.hash import pbkdf2_sha256 as hash
from raven.contrib.flask import Sentry


logging.basicConfig(stream=sys.stdout, level=logging.DEBUG)

logger = logging.getLogger("CLAMAV-REST")

app = Flask("CLAMAV-REST")
app.config.from_object(os.environ['APP_CONFIG'])

try:
    APPLICATION_USERS = dict([user.split("::") for user in app.config["APPLICATION_USERS"].split("\n") if user]) # noqa
except AttributeError:
    APPLICATION_USERS = {}
    logger.warning("No application users configured.")

sentry = Sentry(app, dsn=app.config.get("SENTRY_DSN", None))

auth = HTTPBasicAuth()

if "CLAMD_SOCKET" in app.config:
    cd = clamd.ClamdUnixSocket(path=app.config["CLAMD_SOCKET"])
else:
    cd = clamd.ClamdNetworkSocket(
        host=app.config["CLAMD_HOST"], port=app.config["CLAMD_PORT"])


@auth.verify_password
def verify_pw(username, password):

    app_password = APPLICATION_USERS.get(username, None)

    if not app_password:
        return False

    if hash.verify(password, app_password):
        g.current_user = username
        return True
    else:
        return False


@app.route("/", methods=["GET"])
def healthcheck():

    try:
        cd.ping()
        return "Service OK"
    except clamd.ConnectionError:
        return "Service Unavailable"


@app.route("/scan", methods=["POST"])
@auth.login_required
def scan():

    if len(request.files) != 1:
        return "Provide a single file", 400

    _, file_data = list(request.files.items())[0]

    logger.info("Starting scan for {app_user} of {file_name}".format(
        app_user=g.current_user,
        file_name=file_data.filename
    ))

    start_time = timeit.default_timer()
    resp = cd.instream(file_data)
    elapsed = timeit.default_timer() - start_time

    status = "OK" if resp["stream"][0] == "OK" else "NOTOK"

    logger.info("Scan for {app_user} of {file_name} complete. Took: {elapsed}. Status: {status}".format(
        app_user=g.current_user,
        file_name=file_data.filename,
        elapsed=elapsed,
        status=status
    ))

    return status


if __name__ == "__main__":
    app.run(host=app.config["HOST"], port=app.config["PORT"])
