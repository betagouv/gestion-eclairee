import base64
import io
import logging
import os
import re
import zipfile

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

import xmltodict
from tqdm import tqdm

from .factur_x import read_factur_x
from .models.pivots_xml import PJ, CPPFacturePivot

logger = logging.getLogger(__name__)


LIST_KEYS = ["ParametreIndiv", "CPPFacturePivotUnitaire", "TVA", "Ligne", "PJ", "ValidationUnitaire"]


def parse_xml(xml: str):
    """Parse `xml` string using xmltodict with forced list for known multi-element keys."""
    doc = xmltodict.parse(xml, force_list=LIST_KEYS)
    # Validate we know all the list paths
    list_paths = find_list_paths(doc)
    for path in list_paths:
        tag = path.split(".")[-1]
        assert tag in LIST_KEYS, f"Unknown list: {path}"
    return doc


def find_list_paths(data, parent_path="", found=None):
    if found is None:
        found = set()
    if isinstance(data, dict):
        for key, value in data.items():
            new_path = f"{parent_path}.{key}" if parent_path else key
            find_list_paths(value, new_path, found)
    elif isinstance(data, list):
        found.add(parent_path)
        for item in data:
            find_list_paths(item, f"{parent_path}.*", found)
    return list(found)


def _convert_dict_to_pydantic(data: dict) -> dict:
    """Convert xmltodict output to a structure compatible with pydantic models.
    
    Handles special cases like `#text` nodes and known list keys (`TVAs`, `Lignes`).
    """
    if not data:
        return data

    result = {}
    for key, value in data.items():
        if isinstance(value, dict):
            if len(value.keys()) == 1 and list(value.keys())[0] in LIST_KEYS:
                subkey = list(value.keys())[0]
                if key in ("TVAs", "Lignes"):
                    value = value[subkey]
            if "#text" in value:
                assert set(value.keys()) == {"@xmlns:xs", "@xsi:type", "#text"}, (
                    f"Unknown node {key} {set(value.keys())}"
                )
                value = value["#text"]
        if isinstance(value, dict):
            result[key] = _convert_dict_to_pydantic(value)
        elif isinstance(value, list):
            result[key] = [_convert_dict_to_pydantic(item) for item in value if item]
        else:
            result[key] = value
    return result


def parse_xml_to_obj(xml: str) -> CPPFacturePivot:
    """Parse `xml` string and return a validated `CPPFacturePivot`."""
    # Parse XML to dict
    doc = parse_xml(xml)

    # Get the root element (CPPFacturePivot)
    root_data = doc["CPPFacturePivot"]

    # Convert to pydantic-compatible structure
    converted_data = _convert_dict_to_pydantic(root_data)

    # Create and validate Pydantic model
    return CPPFacturePivot(**converted_data)


def save_file_content(pj: PJ, dirpath: str, name_suffix="") -> str:
    """Save PJ file content to storage.
    
    Extracts the file from `pj.Contenu` (base64-encoded zip), saves it to `dirpath`
    in storage with optional `name_suffix`, and extracts Factur-X XML from PDF files.
    Returns the storage path where the file was saved.
    """
    name, ext = os.path.splitext(pj.NomPJ)
    pj_nom = name + name_suffix + ext
    zip_content = base64.b64decode(pj.Contenu)
    
    # Open the zip file from memory
    zip_info = zipfile.ZipFile(io.BytesIO(zip_content))
    assert len(zip_info.filelist) == 1, f"Multiple files in zip {pj_nom}: {zip_info.filelist}"
    file_info = zip_info.filelist[0]
    assert file_info.filename == pj.NomPJ, f"Name mismatch {file_info.filename} != {pj.NomPJ}"
    
    # Read the file content from zip
    with zip_info.open(file_info.filename) as source:
        file_content = source.read()
    
    # Save the extracted file to storage
    storage_path = os.path.join(dirpath, pj_nom)
    default_storage.save(storage_path, ContentFile(file_content))
    
    # Handle Factur-X extraction for PDF files
    factur_x_xml = None
    if file_info.filename.endswith(".pdf"):
        factur_x_xml = read_factur_x(stream=file_content)
    
    if factur_x_xml is not None:
        factur_x_path = storage_path + ".factur-x.xml"
        default_storage.save(factur_x_path, ContentFile(factur_x_xml))
    
    return storage_path


def extract_pivot_obj(pivot: CPPFacturePivot, output_dir: str, flat_dir: bool):
    """Extract all PJ files from a pivot.
    
    Saves all attachment files from `pivot` to storage under `output_dir`.
    If `flat_dir` is `True`, files are saved directly in `output_dir`.
    If `False`, a subdirectory is created per invoice using the format
    `{supplier_id}_{invoice_id}`.
    """
    for facture in pivot.CPPFactures.CPPFacturePivotUnitaire:
        if flat_dir:
            dirpath = "."
        else:
            dirpath = f"{facture.Fournisseur.Identifiant}_{facture.DonneesFacture.Id}"
        names = set()
        for i, pj in enumerate(facture.PJ, 1):
            if pj.NomPJ in names:
                suffix = f".{i}"
            else:
                suffix = ""
            names.add(pj.NomPJ)
            save_file_content(pj, os.path.join(output_dir, dirpath), name_suffix=suffix)


def extract_pivot_file(filepath: str, output_dir: str, flat_dir: bool) -> None:
    """Extract a pivot XML file.
    
    Parses the XML file at `filepath`, extracts all contained PJ files,
    and saves them to storage under `output_dir` using the directory structure
    specified by `flat_dir`.
    """
    with default_storage.open(filepath, "r") as f:
        xml = f.read()
    pivot = parse_xml_to_obj(xml)
    extract_pivot_obj(pivot, output_dir, flat_dir=flat_dir)


def find_files_by_name(directory, pattern):
    """Recursively search for files matching a regex pattern in storage.
    
    Searches in `directory` and all its subdirectories for files whose names
    match the regex `pattern`. Uses `default_storage` for storage-agnostic operation.
    """
    def _walk_storage(path):
        dirs, files = default_storage.listdir(path)
        
        for file in files:
            if re.match(pattern, file):
                yield os.path.join(path, file)
        
        for dir_name in dirs:
            subpath = os.path.join(path, dir_name)
            yield from _walk_storage(subpath)
    
    yield from _walk_storage(directory)


def extract_facture(filepath: str, base_output_dir: str) -> None:
    """Extract a facture zip file from storage.
    
    Reads the zip file at `filepath` from storage, extracts all files to
    `base_output_dir`/{zip_name}, and processes the contained `PivotS.xml`
    to extract and save all PJ attachments.
    """
    # Extract the name from the zip path
    name = os.path.splitext(os.path.basename(filepath))[0]
    output_dir = os.path.join(base_output_dir, name)
    
    # Check if output directory already exists in storage
    if default_storage.exists(output_dir):
        logger.info(f"{output_dir} already exists, skipping")
        return
    
    # Read the zip file from storage
    with default_storage.open(filepath, "rb") as f:
        zip_data = f.read()
    
    # Extract the zip to memory and save files to storage
    with zipfile.ZipFile(io.BytesIO(zip_data)) as zip_ref:
        # Create the output directory by saving each file
        for file_info in zip_ref.infolist():
            # Skip directory entries
            if file_info.is_dir():
                continue
            # Read file content from zip
            with zip_ref.open(file_info.filename) as source:
                content = source.read()
            # Construct storage path
            target_path = os.path.join(output_dir, file_info.filename)
            # Save content
            default_storage.save(target_path, ContentFile(content))
    
    # Process the pivot file
    pivot_path = os.path.join(output_dir, "PivotS.xml")
    pivot_extract_dir = os.path.join(output_dir, "pivot")
    extract_pivot_file(pivot_path, pivot_extract_dir, flat_dir=True)


def extract_factures(input_dir: str, output_dir: str, ids: list[str] | None = None) -> None:
    """Extract facture zip files from a storage directory.
    
    Processes all `.zip` files in `input_dir`, extracting their contents to `output_dir`.
    If `ids` is provided, only processes zip files whose names match one of the
    IDs in the list (extracted from the filename pattern `*_<id>.zip`).
    """
    _, files = default_storage.listdir(input_dir)
    filtered_files = []
    for filename in files:
        if filename.endswith(".zip"):
            if ids is not None:
                facture_id = re.match(r".*_(\d+).zip", filename).groups(1)
                if facture_id in ids:
                    filtered_files.append(filename)
            elif filename.endswith(".zip"):
                filtered_files.append(filename)
    for filename in tqdm(filtered_files):
        filepath = os.path.join(input_dir, filename)
        extract_facture(filepath, output_dir)


if __name__ == "__main__":
    import django

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "gesec.settings")
    django.setup()

    import argparse

    parser = argparse.ArgumentParser(description="Extract factures from pivot XML files")
    parser.add_argument("ids", nargs="*", help="List of facture IDs to process (without 'facture_' prefix)")
    parser.add_argument("-i", "--input-dir", required=True, help="Input directory containing facture_X.zip files")
    parser.add_argument("-o", "--output-dir", required=True, help="Output directory for extracted files")
    args = parser.parse_args()
    extract_factures(args.input_dir, args.output_dir, ids=args.ids or None)
