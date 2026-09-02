import base64
import io
import zipfile

import pymupdf

from gesec.data.processors.cpro.models.pivots_xml import PJ, CategoriePJ, CPPFacturePivot, TypePJ
from gesec.data.processors.cpro.pivots_xml import (
    extract_facture,
    extract_pivot_file,
    parse_xml_to_obj,
    save_file_content,
)


def create_test_pdf_with_factur_x():
    """Create a test PDF with embedded Factur-X XML using pymupdf."""
    pdf_doc = pymupdf.Document()
    page = pdf_doc.new_page()

    # Add some content to the PDF
    page.insert_text((50, 50), "Test Facture PDF")

    # Create Factur-X XML content
    factur_x_xml = """<?xml version="1.0" encoding="UTF-8"?>
<rsm:CrossIndustryInvoice xmlns:rsm="urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100">
    <rsm:ExchangedDocumentContext>
        <ram:ID>TEST-001</ram:ID>
    </rsm:ExchangedDocumentContext>
    <rsm:Header>
        <ram:ID>FACTURE-001</ram:ID>
        <ram:Name>Test Supplier</ram:Name>
    </rsm:Header>
</rsm:CrossIndustryInvoice>"""

    # Embed the Factur-X XML
    pdf_doc.embfile_add("factur-x.xml", factur_x_xml.encode("utf-8"))

    # Save PDF to bytes
    pdf_bytes = pdf_doc.tobytes()
    return pdf_bytes


def create_test_pj_zip(pj_name: str, file_content: bytes) -> str:
    """Create a base64-encoded zip containing a single file for PJ."""
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        zip_file.writestr(pj_name, file_content)

    return base64.b64encode(zip_buffer.getvalue()).decode("utf-8")


def create_test_pivot_xml() -> str:
    """Create a test PivotS.xml with one invoice and one PJ."""
    return """<?xml version="1.0" encoding="UTF-8"?>
<CPPFacturePivot xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xsi:noNamespaceSchemaLocation="CPPFacturePivot.xsd">
    <Enveloppe>
        <ID>TEST-ENVELOPE-001</ID>
        <Date>2023-01-01</Date>
    </Enveloppe>
    <CPPFactures Compteur="1">
        <CPPFacturePivotUnitaire NumOrdre="1">
            <Fournisseur>
                <TypeIdentifiant>SIREN</TypeIdentifiant>
                <Identifiant>123456789</Identifiant>
                <RaisonSociale>Test Supplier</RaisonSociale>
                <CodePays>FR</CodePays>
                <ModeEmission>E</ModeEmission>
            </Fournisseur>
            <Debiteur>
                <TypeIdentifiant>SIREN</TypeIdentifiant>
                <Identifiant>987654321</Identifiant>
                <Nom>Test Client</Nom>
                <CodeService>TEST</CodeService>
                <NomService>Test Service</NomService>
            </Debiteur>
            <DonneesFacture>
                <Id>FACTURE-001</Id>
                <IdFactureOrigine></IdFactureOrigine>
                <IdCPRO>CPRO-001</IdCPRO>
                <Renvoi>Non</Renvoi>
                <Type>1</Type>
                <Cadre>TEST</Cadre>
                <DateEmissionFacture>2023-01-01</DateEmissionFacture>
                <DateLivraison>2023-01-01</DateLivraison>
                <DateReception>2023-01-01</DateReception>
                <ModePaiement>
                    <Code>VIR</Code>
                    <Libelle>Virement</Libelle>
                </ModePaiement>
                <Devise>EUR</Devise>
                <Montants>
                    <MontantHT>100.00</MontantHT>
                    <MontantTTC>120.00</MontantTTC>
                    <MontantNetAPayer>120.00</MontantNetAPayer>
                </Montants>
                <TVAs>
                    <TVA>
                        <Taux>20.0</Taux>
                        <BaseHt>100.0</BaseHt>
                        <MontantTVA>20.0</MontantTVA>
                    </TVA>
                </TVAs>
                <Engagement>
                    <NumeroEngagement>ENG001</NumeroEngagement>
                </Engagement>
                <Lignes>
                    <Ligne NumOrdre="1">
                        <ReferenceProduit>PROD-001</ReferenceProduit>
                        <PrixUnitaire>100.00</PrixUnitaire>
                        <Quantite>1.0</Quantite>
                        <MontantHT>100.00</MontantHT>
                        <TauxTVA>20.0</TauxTVA>
                    </Ligne>
                </Lignes>
            </DonneesFacture>
            <PJ NumOrdre="1">
                <Contenu>{pdf_pj_content}</Contenu>
                <NomPJ>facture.pdf</NomPJ>
                <CategoriePJ>Facture PDF</CategoriePJ>
                <TypePJ>01</TypePJ>
                <MimeTypePJ>application/pdf</MimeTypePJ>
                <NomPJOrigine>facture.pdf</NomPJOrigine>
            </PJ>
        </CPPFacturePivotUnitaire>
    </CPPFactures>
</CPPFacturePivot>"""


def create_test_facture_zip() -> bytes:
    """Create a test facture zip file containing PivotS.xml."""
    zip_buffer = io.BytesIO()

    # Create PDF content
    pdf_content = create_test_pdf_with_factur_x()

    # Create PJ zip content (base64 encoded)
    pdf_pj_content = create_test_pj_zip("facture.pdf", pdf_content)

    # Create PivotS.xml with the PJ content
    pivot_xml_content = create_test_pivot_xml().replace("{pdf_pj_content}", pdf_pj_content)

    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        zip_file.writestr("PivotS.xml", pivot_xml_content)
        zip_file.writestr("metadata.json", '{"version": "1.0", "date": "2023-01-01"}')

    return zip_buffer.getvalue()


class TestExtractFacture:
    """Test cases for extract_facture function."""

    def test_extract_facture_basic(self, s3_client, caplog):
        """Test basic extraction of a facture zip file."""
        # Get the S3 client and bucket
        bucket = s3_client.Bucket("test-depec")

        # Create test data
        facture_zip_data = create_test_facture_zip()

        # Upload the facture zip file to S3
        input_path = "factures/test_facture_001.zip"
        bucket.put_object(Key=input_path, Body=facture_zip_data)

        # Call extract_facture
        base_output_dir = "extracted"
        result = extract_facture(input_path, base_output_dir)

        # Verify the function returned True for successful processing
        assert result is True

        # Verify the extraction results
        # The function should create:
        # - extracted/test_facture_001/PivotS.xml
        # - extracted/test_facture_001/pivot/facture.pdf
        # - extracted/test_facture_001/pivot/facture.pdf.factur-x.xml (from PDF embedding)

        # Check that PivotS.xml was extracted
        pivot_path = "extracted/test_facture_001/PivotS.xml"
        objs = list(bucket.objects.filter(Prefix=pivot_path))
        assert len(objs) == 1 and objs[0].key == pivot_path

        # Check that the pivot directory was created
        pivot_dir = "extracted/test_facture_001/pivot/"
        objects = list(bucket.objects.filter(Prefix=pivot_dir))
        assert len(objects) >= 1

        # Check that the PDF was extracted from the pivot
        pdf_path = "extracted/test_facture_001/pivot/facture.pdf"
        obj_keys = [obj.key for obj in bucket.objects.all()]
        assert pdf_path in obj_keys

    def test_extract_facture_existing_complete(self, s3_client, caplog):
        """Test that extract_facture skips already processed directories."""
        # Setup S3 mock
        bucket = s3_client.Bucket("test-depec")

        # Create test data
        facture_zip_data = create_test_facture_zip()
        input_path = "factures/test_facture_002.zip"
        base_output_dir = "extracted"

        # First, create a complete extraction (without PARTIAL marker)
        output_dir = "extracted/test_facture_002"

        # Upload the facture zip
        bucket.put_object(Key=input_path, Body=facture_zip_data)

        # Create the PivotS.xml to simulate existing extraction
        pivot_xml_content = create_test_pivot_xml()
        bucket.put_object(Key=f"{output_dir}/PivotS.xml", Body=pivot_xml_content)

        # Call extract_facture - should skip and return False
        with caplog.at_level("INFO"):
            result = extract_facture(input_path, base_output_dir)

        # Verify the function returned False (skipped)
        assert result is False

        # Verify the log message indicates skipping
        assert "already exists, skipping" in caplog.text

    def test_extract_facture_existing_partial(self, s3_client, caplog):
        """Test that extract_facture deletes and reprocesses partial extractions."""
        # Setup S3 mock
        bucket = s3_client.Bucket("test-depec")

        # Create test data
        facture_zip_data = create_test_facture_zip()
        input_path = "factures/test_facture_003.zip"
        base_output_dir = "extracted"

        # Upload the facture zip
        bucket.put_object(Key=input_path, Body=facture_zip_data)

        # Create a partial extraction (with PARTIAL marker)
        output_dir = "extracted/test_facture_003"
        partial_path = f"{output_dir}/PARTIAL"
        bucket.put_object(Key=partial_path, Body=b"partial")

        # Create PivotS.xml to simulate partial extraction
        pivot_xml_content = create_test_pivot_xml()
        bucket.put_object(Key=f"{output_dir}/PivotS.xml", Body=pivot_xml_content)

        # Call extract_facture - should delete partial and reprocess
        with caplog.at_level("INFO"):
            result = extract_facture(input_path, base_output_dir)

        # Verify the function returned True (processed successfully)
        assert result is True

        # Verify the log messages indicate partial deletion and reprocessing
        assert "already exists but is partial, deleting" in caplog.text
        assert "delete complete, now processing it" in caplog.text

        # Verify that files were extracted (PARTIAL was deleted and reprocessed)
        obj_keys = [obj.key for obj in bucket.objects.all()]
        assert f"{output_dir}/PivotS.xml" in obj_keys

    def test_extract_facture_multiple_files(self, s3_client):
        """Test extraction of a facture zip with multiple files."""
        # Setup S3 mock
        bucket = s3_client.Bucket("test-depec")

        # Create test data with multiple files in the zip
        zip_buffer = io.BytesIO()

        # Create PDF content
        pdf_content = create_test_pdf_with_factur_x()
        pdf_pj_content = create_test_pj_zip("facture.pdf", pdf_content)

        # Create PivotS.xml
        pivot_xml = create_test_pivot_xml().replace("{pdf_pj_content}", pdf_pj_content)

        # Create additional test file
        additional_content = b'{"test": "data"}'

        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
            zip_file.writestr("PivotS.xml", pivot_xml)
            zip_file.writestr("metadata.json", additional_content)
            zip_file.writestr("readme.txt", b"Test readme file")

        facture_zip_data = zip_buffer.getvalue()

        # Upload and extract
        input_path = "factures/test_facture_004.zip"
        bucket.put_object(Key=input_path, Body=facture_zip_data)

        base_output_dir = "extracted"
        result = extract_facture(input_path, base_output_dir)

        # Verify the function returned True for successful processing
        assert result is True

        # Verify all files were extracted
        output_dir = "extracted/test_facture_004"
        obj_keys = [obj.key for obj in bucket.objects.all()]

        # Check PivotS.xml
        assert f"{output_dir}/PivotS.xml" in obj_keys

        # Check metadata.json
        assert f"{output_dir}/metadata.json" in obj_keys

        # Check readme.txt
        assert f"{output_dir}/readme.txt" in obj_keys

        # Check that pivot directory was created with PDF
        assert f"{output_dir}/pivot/facture.pdf" in obj_keys


class TestExtractPivotFile:
    """Test cases for extract_pivot_file function."""

    def test_extract_pivot_file_basic(self, s3_client):
        """Test basic extraction of a pivot XML file."""
        # Setup S3 mock
        bucket = s3_client.Bucket("test-depec")

        # Create PDF content
        pdf_content = create_test_pdf_with_factur_x()
        pdf_pj_content = create_test_pj_zip("facture.pdf", pdf_content)

        # Create PivotS.xml
        pivot_xml = create_test_pivot_xml().replace("{pdf_pj_content}", pdf_pj_content)

        # Upload PivotS.xml
        input_path = "pivots/test_pivot.xml"
        bucket.put_object(Key=input_path, Body=pivot_xml)

        # Call extract_pivot_file
        output_dir = "extracted_pivots"
        extract_pivot_file(input_path, output_dir, flat_dir=True)

        # Verify extraction
        obj_keys = [obj.key for obj in bucket.objects.all()]
        assert f"{output_dir}/facture.pdf" in obj_keys

        # For PDF files, Factur-X should also be extracted
        assert f"{output_dir}/facture.pdf.factur-x.xml" in obj_keys


class TestParseXmlToObj:
    """Test cases for parse_xml_to_obj function."""

    def test_parse_xml_to_obj_basic(self):
        """Test parsing XML to CPPFacturePivot object."""
        xml_content = """<?xml version="1.0" encoding="UTF-8"?>
<CPPFacturePivot xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xsi:noNamespaceSchemaLocation="CPPFacturePivot.xsd">
    <Enveloppe>
        <ID>TEST-ENVELOPE-001</ID>
        <Date>2023-01-01</Date>
    </Enveloppe>
    <CPPFactures Compteur="1">
        <CPPFacturePivotUnitaire NumOrdre="1">
            <Fournisseur>
                <TypeIdentifiant>SIREN</TypeIdentifiant>
                <Identifiant>123456789</Identifiant>
                <RaisonSociale>Test Supplier</RaisonSociale>
                <CodePays>FR</CodePays>
                <ModeEmission>E</ModeEmission>
            </Fournisseur>
            <Debiteur>
                <TypeIdentifiant>SIREN</TypeIdentifiant>
                <Identifiant>987654321</Identifiant>
                <Nom>Test Client</Nom>
                <CodeService>TEST</CodeService>
                <NomService>Test Service</NomService>
            </Debiteur>
            <DonneesFacture>
                <Id>FACTURE-001</Id>
                <IdFactureOrigine></IdFactureOrigine>
                <IdCPRO>CPRO-001</IdCPRO>
                <Renvoi>Non</Renvoi>
                <Type>1</Type>
                <Cadre>TEST</Cadre>
                <DateEmissionFacture>2023-01-01</DateEmissionFacture>
                <DateLivraison>2023-01-01</DateLivraison>
                <DateReception>2023-01-01</DateReception>
                <ModePaiement>
                    <Code>VIR</Code>
                    <Libelle>Virement</Libelle>
                </ModePaiement>
                <Devise>EUR</Devise>
                <Montants>
                    <MontantHT>100.00</MontantHT>
                    <MontantTTC>120.00</MontantTTC>
                    <MontantNetAPayer>120.00</MontantNetAPayer>
                </Montants>
                <TVAs>
                    <TVA>
                        <Taux>20.0</Taux>
                        <BaseHt>100.0</BaseHt>
                        <MontantTVA>20.0</MontantTVA>
                    </TVA>
                </TVAs>
                <Engagement>
                    <NumeroEngagement>ENG001</NumeroEngagement>
                </Engagement>
                <Lignes>
                    <Ligne NumOrdre="1">
                        <ReferenceProduit>PROD-001</ReferenceProduit>
                        <PrixUnitaire>100.00</PrixUnitaire>
                        <Quantite>1.0</Quantite>
                        <MontantHT>100.00</MontantHT>
                        <TauxTVA>20.0</TauxTVA>
                    </Ligne>
                </Lignes>
            </DonneesFacture>
            <PJ NumOrdre="1">
                <Contenu>YQ==</Contenu>
                <NomPJ>test.txt</NomPJ>
                <CategoriePJ>Pièce jointe standard</CategoriePJ>
                <TypePJ>01</TypePJ>
                <MimeTypePJ>text/plain</MimeTypePJ>
            </PJ>
        </CPPFacturePivotUnitaire>
    </CPPFactures>
</CPPFacturePivot>"""

        # Parse the XML
        pivot = parse_xml_to_obj(xml_content)

        # Verify the structure
        assert isinstance(pivot, CPPFacturePivot)
        assert pivot.CPPFactures.Compteur == 1
        assert len(pivot.CPPFactures.CPPFacturePivotUnitaire) == 1

        facture = pivot.CPPFactures.CPPFacturePivotUnitaire[0]
        assert facture.Fournisseur.Identifiant == "123456789"
        assert facture.Debiteur.Nom == "Test Client"
        assert facture.DonneesFacture.Id == "FACTURE-001"
        assert len(facture.PJ) == 1
        assert facture.PJ[0].NomPJ == "test.txt"


class TestSaveFileContent:
    """Test cases for save_file_content function."""

    def test_save_file_content_pdf_with_factur_x(self, s3_client):
        """Test saving PDF file content with embedded Factur-X."""
        # Setup S3 mock
        bucket = s3_client.Bucket("test-depec")

        # Create PDF with embedded Factur-X
        pdf_content = create_test_pdf_with_factur_x()

        # Create PJ object using alias
        pdf_pj_content = create_test_pj_zip("facture.pdf", pdf_content)

        pj = PJ(
            **{
                "@NumOrdre": 1,
                "Contenu": pdf_pj_content,
                "NomPJ": "facture.pdf",
                "CategoriePJ": CategoriePJ.FACTURE_PDF,
                "TypePJ": TypePJ.TYPE_1,
                "MimeTypePJ": "application/pdf",
                "NomPJOrigine": "facture.pdf",
            }
        )

        # Call save_file_content
        dirpath = "test_save_content"
        saved_path = save_file_content(pj, dirpath)

        # Verify the file was saved
        obj_keys = [obj.key for obj in bucket.objects.all()]
        assert saved_path in obj_keys

        # For PDF files, Factur-X should also be extracted
        factur_x_path = saved_path + ".factur-x.xml"
        assert factur_x_path in obj_keys

    def test_save_file_content_non_pdf(self, s3_client):
        """Test saving non-PDF file content."""
        # Setup S3 mock
        bucket = s3_client.Bucket("test-depec")

        # Create simple text content
        text_content = b"Test file content"
        text_pj_content = create_test_pj_zip("test.txt", text_content)

        # Create PJ object using alias
        pj = PJ(
            **{
                "@NumOrdre": 1,
                "Contenu": text_pj_content,
                "NomPJ": "test.txt",
                "CategoriePJ": CategoriePJ.PJ_STANDARD,
                "TypePJ": TypePJ.TYPE_1,
                "MimeTypePJ": "text/plain",
                "NomPJOrigine": "test.txt",
            }
        )

        # Call save_file_content
        dirpath = "test_save_content"
        saved_path = save_file_content(pj, dirpath)

        # Verify the file was saved
        obj_keys = [obj.key for obj in bucket.objects.all()]
        assert saved_path in obj_keys

        # For non-PDF files, no Factur-X should be extracted
        factur_x_path = saved_path + ".factur-x.xml"
        assert factur_x_path not in obj_keys
