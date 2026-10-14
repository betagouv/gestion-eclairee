privateweb: gunicorn --config gunicorn_conf.py gesec.front.wsgi
mcp: python -m mcpserver.server
postdeploy: if [ "$DISABLE_MIGRATE" != "1" ]; then python manage.py migrate; fi
