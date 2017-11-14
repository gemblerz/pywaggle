# Conversion for onset rain gauge

def convert(value):
    raw_c = value['onset_rain']
    value['onset_rain'] = (raw_c * 0.01, 'inch')

    return value