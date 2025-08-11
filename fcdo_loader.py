import pyexcel_ods3

def load_fcdo_names(path):
    data = pyexcel_ods3.get_data(path)
    # Find the first sheet
    sheet = next(iter(data.values()))
    # Column C is index 2, skip header if present
    names = []
    for row in sheet:
        if len(row) > 2:
            names.append(str(row[2]))
    return names
