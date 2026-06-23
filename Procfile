web: gunicorn --config gunicorn_conf.py gesec.front.wsgi
postdeploy: if [ "$DISABLE_MIGRATE" != "1" ]; then python manage.py migrate; fi
