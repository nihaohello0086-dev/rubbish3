# app/services/document_processor.py
"""
Document processing service for extracting text from various file formats.
Supports: PDF, TXT, DOCX files with robust error handling and multi-library fallbacks.
"""
import os
import tempfile
from pathlib import Path
from typing import Optional, Callable, Any
from app.utils.logger import logger  # 导入日志器

# Optional dependency imports with graceful fallback handling
try:
    import PyPDF2

    logger.info("PyPDF2 library available")
except ImportError:
    PyPDF2 = None  # type: ignore[assignment]
    logger.warning("PyPDF2 not installed")

try:
    import fitz  # PyMuPDF - better for complex layouts and mathematical content

    logger.info("PyMuPDF (fitz) library available")
except ImportError:
    fitz = None  # type: ignore[assignment]
    logger.warning("PyMuPDF not installed")

try:
    from docx import Document  # python-docx for .docx files

    logger.info("python-docx library available")
except ImportError:
    Document = None  # type: ignore[assignment]
    logger.warning("python-docx not installed")

try:
    import mammoth  # Alternative Word processor with better formatting preservation

    logger.info("mammoth library available")
except ImportError:
    mammoth = None  # type: ignore[assignment]
    logger.warning("mammoth not installed")


if fitz:
    logger.info("PyMuPDF (fitz) is available for PDF-to-Image conversion")


class DocumentProcessingError(Exception):
    """Custom exception raised when document processing operations fail."""

    pass


def _clean_text(text: str) -> str:
    """
    Clean and normalize extracted text for consistent formatting.

    This function handles:
    - Cross-platform line ending normalization (Windows \r\n -> Unix \n)
    - Excessive whitespace consolidation while preserving paragraph structure
    - Leading/trailing whitespace removal

    Args:
        text: Raw text extracted from document

    Returns:
        Cleaned and normalized text string
    """
    if not text:
        return ""

    import re

    original_len = len(text)

    # Normalize line endings from different operating systems
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # Collapse 3+ consecutive newlines into 2 to preserve paragraph breaks
    # This maintains document structure while cleaning up excessive spacing
    text = re.sub(r"\n{3,}", "\n\n", text)

    # Compress multiple whitespace characters (space, tab, form feed, vertical tab)
    # into single spaces, but don't cross newline boundaries
    text = re.sub(r"[ \t\f\v]+", " ", text)

    cleaned = text.strip()
    logger.debug(f"Text cleaned: {original_len} -> {len(cleaned)} characters")

    return cleaned


def _safe_add(buf: list[str], piece: Optional[str]) -> None:
    """
    Safely append non-empty text content to buffer.

    This helper prevents empty strings from being added to the text buffer,
    reducing unnecessary processing and improving final text quality.

    Args:
        buf: Text buffer to append to
        piece: Text piece to add (may be None or empty)
    """
    if piece and piece.strip():
        buf.append(piece)
        logger.debug(f"Added {len(piece)} characters to buffer")


def _fitz_extract_page_text(page: Any) -> str:
    """
    Extract text from a PyMuPDF page object using multiple API compatibility approaches.

    PyMuPDF has evolved over time with different method signatures and names.
    This function tries multiple approaches to maximize compatibility across versions:

    1. get_text("text") - Modern explicit format specification
    2. get_text() - Modern default behavior
    3. getText("text") - Legacy API with format
    4. getText() - Legacy API default

    Args:
        page: PyMuPDF page object from any version

    Returns:
        Extracted text content from the page

    Raises:
        AttributeError: If no compatible text extraction method is found
    """
    logger.debug("Extracting text from PyMuPDF page")

    # Try modern API: get_text with explicit "text" format
    get_text: Optional[Callable[..., str]] = getattr(page, "get_text", None)
    if callable(get_text):
        try:
            result = get_text("text")
            logger.debug("Extracted text using get_text('text')")
            return result
        except TypeError:
            # Some versions don't accept format parameter or have different defaults
            try:
                result = get_text()
                logger.debug("Extracted text using get_text()")
                return result
            except Exception:
                pass  # Continue to next method

    # Try legacy API: getText (older PyMuPDF versions)
    getText: Optional[Callable[..., str]] = getattr(page, "getText", None)
    if callable(getText):
        try:
            # Try with format specification first
            try:
                result = getText("text")
                logger.debug("Extracted text using getText('text')")
                return result
            except Exception:
                # Fall back to default behavior
                result = getText()
                logger.debug("Extracted text using getText()")
                return result
        except Exception:
            pass  # Continue to final fallback

    # Final attempt: try get_text without parameters (some forks/stubs)
    if callable(get_text):
        try:
            result = get_text()
            logger.debug("Extracted text using get_text() fallback")
            return result
        except Exception:
            pass

    # All methods failed - this indicates a serious compatibility issue
    logger.error("No compatible text extraction method found on PyMuPDF page object")
    raise AttributeError(
        "No compatible text extraction method found on PyMuPDF page object"
    )


def pdf_to_image_file(file_path: str, dpi: int = 300) -> str:
    """
    Convert the first page of a PDF to a temporary PNG image file.
    
    Args:
        file_path: Path to the source PDF file.
        dpi: Resolution for the output image (default 300 for high quality OCR).
        
    Returns:
        Path to the created temporary image file.
        
    Raises:
        DocumentProcessingError: If conversion fails or PyMuPDF is missing.
    """
    logger.info(f"Converting PDF to image: {file_path}")
    
    if not fitz:
        raise DocumentProcessingError("PyMuPDF (fitz) is required for PDF-to-Image conversion.")
        
    try:
        doc = fitz.open(file_path)
        if doc.page_count < 1:
            raise DocumentProcessingError("PDF is empty")
            
        # 只取第一页
        page = doc.load_page(0)
        pix = page.get_pixmap(dpi=dpi)
        
        # 创建临时文件保存图片
        with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp_img:
            tmp_img_path = tmp_img.name
            
        pix.save(tmp_img_path)
        doc.close()
        
        logger.debug(f"PDF page converted to image: {tmp_img_path}")
        return tmp_img_path
        
    except Exception as e:
        logger.error(f"Failed to convert PDF to image: {e}")
        raise DocumentProcessingError(f"Failed to convert PDF to image: {e}")


def pdf_to_text(file_path: str) -> str:
    """
    Extract text from PDF files using multiple fallback libraries for maximum reliability.

    Processing priority:
    1. PyMuPDF (fitz) - Superior for complex layouts, mathematical content, and multi-column text
    2. PyPDF2 - Lightweight fallback for simple PDF documents

    The function gracefully handles library unavailability and processing errors by
    attempting each method in sequence until success or all options are exhausted.

    Args:
        file_path: Path to the PDF file to process

    Returns:
        Extracted and cleaned text content

    Raises:
        DocumentProcessingError: If file not found, no libraries available, or extraction fails
    """
    logger.info(f"Processing PDF file: {file_path}")

    path = Path(file_path)
    if not path.exists():
        logger.error(f"PDF file not found: {file_path}")
        raise DocumentProcessingError(f"PDF file not found: {file_path}")

    page_texts: list[str] = []

    # Method 1: PyMuPDF (fitz) - Preferred for quality and feature support
    if fitz:
        logger.debug("Attempting PDF extraction with PyMuPDF")
        try:
            doc = fitz.open(str(path))
            try:
                logger.debug(f"PDF has {doc.page_count} pages")

                # Process each page individually to handle per-page errors gracefully
                for page_num in range(doc.page_count):
                    page = doc.load_page(page_num)
                    try:
                        text_piece = _fitz_extract_page_text(page)
                        _safe_add(page_texts, text_piece)
                        logger.debug(
                            f"Extracted {len(text_piece)} chars from page {page_num}"
                        )
                    except Exception as e:
                        # Individual page failure - log and continue processing
                        # This prevents one corrupted page from failing the entire document
                        logger.warning(
                            f"Failed to extract text from page {page_num}: {e}"
                        )
                        # Add empty content to maintain page structure
                        _safe_add(page_texts, "")

                    # Add page break marker to prevent text from different pages merging
                    page_texts.append("\n")
            finally:
                # Ensure document is always closed to free memory
                doc.close()
                logger.debug("PyMuPDF document closed")

            # Check if we successfully extracted any text
            combined = "".join(page_texts)
            if combined.strip():
                logger.info(f"PyMuPDF extracted {len(combined)} total characters")
                return _clean_text(combined)

        except Exception as e:
            # PyMuPDF completely failed - log warning and try fallback
            logger.warning(
                f"PyMuPDF processing failed: {e}, attempting PyPDF2 fallback..."
            )

    # Clear buffer for PyPDF2 attempt (in case PyMuPDF partially succeeded)
    page_texts.clear()

    # Method 2: PyPDF2 - Fallback option for basic PDF text extraction
    if PyPDF2:
        logger.debug("Attempting PDF extraction with PyPDF2")
        try:
            with open(file_path, "rb") as f:
                reader = PyPDF2.PdfReader(f)
                logger.debug(f"PDF has {len(reader.pages)} pages")

                for i, page in enumerate(reader.pages):
                    try:
                        # PyPDF2.extract_text() may return None, so handle gracefully
                        piece = page.extract_text() or ""
                        _safe_add(page_texts, piece)
                        logger.debug(f"Extracted {len(piece)} chars from page {i}")
                        page_texts.append("\n")  # Page separator
                    except Exception as e:
                        logger.warning(
                            f"Failed to extract text from page {i} with PyPDF2: {e}"
                        )
                        page_texts.append("\n")  # Maintain page structure

            combined = "".join(page_texts)
            if combined.strip():
                logger.info(f"PyPDF2 extracted {len(combined)} total characters")
                return _clean_text(combined)

        except Exception as e:
            logger.error(f"PyPDF2 processing failed: {e}")

    # Check if any PDF processing library is available
    if not (fitz or PyPDF2):
        logger.error("No PDF processing library available")
        raise DocumentProcessingError(
            "No PDF processing library available. Please install a PDF processor:\n"
            "pip install PyMuPDF  # Recommended for better quality\n"
            "pip install PyPDF2   # Lightweight alternative"
        )

    # All processing methods failed or returned empty content
    logger.error("Could not extract text from PDF")
    raise DocumentProcessingError(
        "Could not extract text from PDF. Possible causes:\n"
        "- PDF contains only images/scanned content (requires OCR)\n"
        "- PDF is password protected or corrupted\n"
        "- PDF uses unsupported encoding or format"
    )


def txt_to_text(file_path: str) -> str:
    """
    Extract text from plain text files with automatic encoding detection.

    Tries multiple common encodings to handle files from different sources and regions:
    - UTF-8: Modern standard, handles all Unicode characters
    - UTF-8-BOM: UTF-8 with byte order mark (common in Windows)
    - Latin1: Western European languages
    - CP1252: Windows Western European encoding
    - ISO-8859-1: Standard Western European encoding

    Args:
        file_path: Path to the text file

    Returns:
        Decoded and cleaned text content

    Raises:
        DocumentProcessingError: If file not found or no encoding works
    """
    logger.info(f"Processing text file: {file_path}")

    path = Path(file_path)
    if not path.exists():
        logger.error(f"Text file not found: {file_path}")
        raise DocumentProcessingError(f"Text file not found: {file_path}")

    # Try encodings in order of preference (most common to least)
    encodings = ["utf-8", "utf-8-sig", "latin1", "cp1252", "iso-8859-1"]

    for enc in encodings:
        try:
            logger.debug(f"Trying encoding: {enc}")
            with open(file_path, "r", encoding=enc) as f:
                content = f.read()
                logger.info(
                    f"Successfully read text file with {enc} encoding, {len(content)} characters"
                )
                return _clean_text(content)
        except UnicodeDecodeError:
            logger.debug(f"Encoding {enc} failed")
            continue
        except Exception as e:
            # Unexpected error (file permissions, I/O error, etc.)
            logger.error(f"Failed to read text file: {e}")
            raise DocumentProcessingError(f"Failed to read text file: {e}")

    # None of the encodings worked
    logger.error(f"Could not decode text file with any supported encoding")
    raise DocumentProcessingError(
        f"Could not decode text file with any supported encoding: {encodings}. "
        f"File may use an uncommon encoding or be corrupted."
    )


def docx_to_text(file_path: str) -> str:
    """
    Extract text from Word documents using multiple processing libraries.

    Processing priority:
    1. python-docx: Native .docx support with good structure preservation
    2. mammoth: Alternative processor with better formatting preservation for complex documents

    Both libraries handle different aspects of Word documents well:
    - python-docx: Better for simple text extraction and paragraph structure
    - mammoth: Better for complex formatting and legacy .doc files

    Args:
        file_path: Path to the Word document (.docx or .doc)

    Returns:
        Extracted and cleaned text content

    Raises:
        DocumentProcessingError: If file not found, no libraries available, or extraction fails
    """
    logger.info(f"Processing Word document: {file_path}")

    path = Path(file_path)
    if not path.exists():
        logger.error(f"Word document not found: {file_path}")
        raise DocumentProcessingError(f"Word document not found: {file_path}")

    text_content = ""
    ext = path.suffix.lower()

    # Method 1: python-docx (preferred for .docx files)
    if Document and ext == ".docx":
        logger.debug("Attempting extraction with python-docx")
        try:
            doc = Document(file_path)
            # Extract all paragraphs with text content
            paragraphs = []
            para_count = 0
            for p in doc.paragraphs:
                if p.text and p.text.strip():
                    paragraphs.append(p.text)
                    para_count += 1

            logger.debug(f"Extracted {para_count} paragraphs from Word document")
            text_content = "\n".join(paragraphs)

            if text_content.strip():
                logger.info(f"python-docx extracted {len(text_content)} characters")
                return _clean_text(text_content)

        except Exception as e:
            logger.warning(
                f"python-docx processing failed: {e}, trying mammoth fallback..."
            )

    # Method 2: mammoth (fallback, works with both .docx and .doc files)
    if mammoth:
        logger.debug("Attempting extraction with mammoth")
        try:
            with open(file_path, "rb") as fp:
                # mammoth extracts raw text without formatting
                result = mammoth.extract_raw_text(fp)
                text_content = result.value or ""

                # Check for warnings in mammoth result
                if hasattr(result, "messages") and result.messages:
                    for msg in result.messages:
                        logger.debug(f"Mammoth message: {msg}")

                if text_content.strip():
                    logger.info(f"mammoth extracted {len(text_content)} characters")
                    return _clean_text(text_content)

        except Exception as e:
            logger.error(f"mammoth processing failed: {e}")

    # Check if any Word processing library is available
    if not (Document or mammoth):
        logger.error("No Word document processing library available")
        raise DocumentProcessingError(
            "No Word document processing library available. Please install:\n"
            "pip install python-docx  # Recommended for .docx files\n"
            "pip install mammoth      # Alternative with .doc support"
        )

    # All processing methods failed or returned empty content
    logger.error("Could not extract text from Word document")
    raise DocumentProcessingError(
        "Could not extract text from Word document. Possible causes:\n"
        "- Document is password protected\n"
        "- Document is corrupted or uses unsupported format\n"
        "- Document contains only images or objects without text"
    )


def detect_document_type(file_path: str) -> Optional[str]:
    """
    Detect document type based on file extension.

    This is a simple but effective approach for determining processing method.
    More sophisticated detection could examine file headers, but extension-based
    detection is sufficient for most use cases and is much faster.

    Args:
        file_path: Path to the document file

    Returns:
        Document type string ('pdf', 'txt', 'docx', 'doc') or None if unsupported
    """
    logger.debug(f"Detecting document type for: {file_path}")

    path = Path(file_path)
    if not path.exists():
        logger.warning(f"File does not exist: {file_path}")
        return None

    ext = path.suffix.lower()

    # Map file extensions to processing types
    extension_map = {
        ".pdf": "pdf",
        ".txt": "txt",
        ".docx": "docx",
        ".doc": "doc",  # Handled by mammoth if available
    }

    doc_type = extension_map.get(ext)
    logger.debug(f"Detected document type: {doc_type} (extension: {ext})")

    return doc_type


def process_document(file_path: str) -> str:
    """
    Universal document processor that automatically detects file type and extracts text.

    This is a convenience function that combines type detection with appropriate
    processing method selection. It provides a single entry point for processing
    any supported document type.

    Args:
        file_path: Path to the document file

    Returns:
        Extracted and cleaned text content

    Raises:
        DocumentProcessingError: If file type unsupported or processing fails
    """
    logger.info(f"Processing document: {file_path}")

    doc_type = detect_document_type(file_path)
    logger.debug(f"Detected document type: {doc_type}")

    # Route to appropriate processor based on detected type
    if doc_type == "pdf":
        return pdf_to_text(file_path)
    elif doc_type == "txt":
        return txt_to_text(file_path)
    elif doc_type in ("docx", "doc"):
        return docx_to_text(file_path)
    else:
        supported_types = ["pdf", "txt", "docx", "doc"]
        logger.error(f"Unsupported document type for file: {file_path}")
        raise DocumentProcessingError(
            f"Unsupported document type for file: {file_path}\n"
            f"Supported types: {supported_types}"
        )


# Library capability checking functions for system diagnostics
def check_pdf_support() -> dict:
    """
    Check availability of PDF processing libraries.

    Returns:
        Dictionary mapping library names to availability status
    """
    logger.debug("Checking PDF support")
    support = {"PyMuPDF": fitz is not None, "PyPDF2": PyPDF2 is not None}
    logger.debug(f"PDF support status: {support}")
    return support


def check_docx_support() -> dict:
    """
    Check availability of Word document processing libraries.

    Returns:
        Dictionary mapping library names to availability status
    """
    logger.debug("Checking DOCX support")
    support = {"python-docx": Document is not None, "mammoth": mammoth is not None}
    logger.debug(f"DOCX support status: {support}")
    return support


def get_processing_capabilities() -> dict:
    """
    Get comprehensive overview of document processing capabilities.

    This function is useful for system diagnostics and capability reporting.
    It shows which document types can be processed and which libraries are available.

    Returns:
        Dictionary containing:
        - Document type support status (pdf, docx, txt)
        - Available libraries for each type
        - Overall capability summary
    """
    logger.info("Getting document processing capabilities")

    pdf_libs = check_pdf_support()
    docx_libs = check_docx_support()

    capabilities = {
        # High-level capability flags
        "pdf": any(pdf_libs.values()),
        "docx": any(docx_libs.values()),
        "txt": True,  # Always supported (built-in Python functionality)
        # Detailed library availability
        "libraries": {"pdf": pdf_libs, "docx": docx_libs},
    }

    logger.info(
        f"Processing capabilities: PDF={capabilities['pdf']}, DOCX={capabilities['docx']}, TXT={capabilities['txt']}"
    )

    return capabilities
