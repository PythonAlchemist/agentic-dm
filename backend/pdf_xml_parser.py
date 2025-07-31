import pymupdf4llm


def convert_pdf_to_markdown(pdf_path):
    """
    Converts a PDF file to Markdown format using pymupdf4llm.

    Args:
        pdf_path (str): Path to the PDF file.

    Returns:
        str: The content of the PDF in Markdown format.
    """
    try:
        md_text = pymupdf4llm.to_markdown(pdf_path)
    except Exception as e:
        print(f"Error converting PDF to Markdown: {e}")
        md_text = ""
    return md_text


if __name__ == "__main__":
    # Example usage
    pdf_path = "data/armyofthedamned.pdf"  # Update with the correct path
    markdown_content = convert_pdf_to_markdown(pdf_path)
    print(markdown_content)
