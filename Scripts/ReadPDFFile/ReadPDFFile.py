import demistomock as demisto
from CommonServerPython import *

import pdfx
from pdfminer.psparser import PSEOF
from pdfminer.pdfdocument import PDFEncryptionError
import sys
reload(sys)
sys.setdefaultencoding("utf-8")

entry_id = demisto.args()["entryID"]


def mark_suspicious(suspicious_reason):
    """Missing EOF, file may be corrupted or suspicious file"""

    dbot = {
        "DBotScore":
            {
                "Indicator": entry_id,
                "Type": "file",
                "Vendor": "PDFx",
                "Score": 2
            }
    }

    human_readable = "{}, file marked as suspicious for entry id: {}".format(suspicious_reason, entry_id)

    return_outputs(human_readable, dbot, {})


#File entity
pdf_file = {
    "EntryID" : entry_id
}

#URLS
URLs = []

maxFileSize = demisto.get(demisto.args(), "maxFileSize")
if maxFileSize:
    maxFileSize = int(maxFileSize)
else:
    maxFileSize = 1024**2
res = demisto.executeCommand("getFilePath", {"id": entry_id})
if isError(res[0]):
    demisto.results(res)
else:
    path = demisto.get(res[0],"Contents.path")
    if path:
        try:
            pdf = pdfx.PDFx(path)
        except PSEOF:
            mark_suspicious('Missing EOF')
            sys.exit(0)
        except PDFEncryptionError:
            mark_suspicious('Possibly encrypted file')
            sys.exit(0)

        if not pdf:
            demisto.results({
                "Type": entryTypes["error"],
                "ContentsFormat": formats["text"],
                "Contents" : "Could not load pdf file in EntryID {0}".format(entry_id)
            })
            sys.exit(0)


        # Get metadata:
        metadata = pdf.get_metadata()

        # Get text:
        text = pdf.get_text()

        # Get URLs:
        references_dict = pdf.get_references_as_dict()
        if "url" in references_dict.keys():
            for url in references_dict["url"]:
                URLs.append({"Data":url})

        #Add Text to file entity
        pdf_file["Text"] = text

        #Add Metadata to file entity
        for k in metadata.keys():
            pdf_file[k] = metadata[k]

        md = "### Metadata\n"
        md += "* " if metadata else ""
        md += "\n* ".join(["{0}: {1}".format(k,v) for k,v in metadata.iteritems()])

        md += "\n### URLs\n"
        md += "* " if URLs else ""
        md += "\n* ".join(["{0}".format(str(k["Data"])) for k in URLs])

        md += "\n### Text"
        md += "\n{0}".format(text)

        demisto.results({"Type" : entryTypes["note"],
                         "ContentsFormat" : formats["markdown"],
                         "Contents" : md,
                         "HumanReadable": md,
                         "EntryContext": {"File(val.EntryID == obj.EntryID)" : pdf_file, "URL" : URLs}
                         })

        all_pdf_data = ""
        if metadata:
            for k,v in metadata.iteritems():
                all_pdf_data += str(v)
        if text:
            all_pdf_data += text
        if URLs:
            for u in URLs:
                u = u["Data"] + " "
                all_pdf_data += u

        # Extract indicators (omitting context output, letting auto-extract work)
        indicators_hr = demisto.executeCommand("extractIndicators", {
            "text": all_pdf_data})[0][u"Contents"]
        demisto.results({
            "Type": entryTypes["note"],
            "ContentsFormat": formats["json"],
            "Contents": indicators_hr,
            "HumanReadable": indicators_hr
        })

    else:
        demisto.results({
            "Type" : entryTypes["error"],
            "ContentsFormat" : formats["text"],
            "Contents" : "EntryID {0} path could not be found".format(entry_id)
        })
