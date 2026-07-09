#!/bin/bash

set -eux

MEDIA_DIR=../recette_media_gesec
if [ -d "$MEDIA_DIR" ]; then
  rm -r ../recette_media_gesec
fi
cp -r ../gesec_recette/dataset/ ../recette_media_gesec

export ENV_FILE=../gesec-recette.env

./manage.py migrate

# Unzip factures
python -m gesec.data.processors.cpro.pivots_xml -i $MEDIA_DIR/cpro/factures -o $MEDIA_DIR/cpro/factures_unzipped

./manage.py launch_pipeline
DUMP_FOLDER=../gesec/testing/dumps_$(date +"%Y%m%d_%H%M%S")
python -m gesec.data.pipeline.testing.dump gesec_facture gesec_facture_ligne -o  $DUMP_FOLDER
python -m gesec.data.pipeline.testing.test ../gesec_recette/result $DUMP_FOLDER
