# datasets model field value choices

COMMENT_TAGS = [
    ('bad_link','Incorrect match/link'),
    ('bad_type','Incorrect place type'),
    ('typo','Typo'),
    ('other','Other'),
]

FORMATS = [
    ('delimited', 'Delimited'),
    ('lpf', 'Linked Places (GeoJSON-LDT)'),
    ('direct', 'Inserted to db directly'),
]

DATATYPES = [
    ('place', 'Places'),
    ('anno', 'Annotations'),
    ('source', 'Sources')
]

STATUS = [
    ('format_error', 'Invalid format'),
    ('format_ok', 'Valid format'),
    ('in_database', 'Inserted to database'),
    ('uploaded', 'File uploaded'),
    ('ready', 'Ready for submittal'),
    ('accepted', 'Accepted'),
]

AUTHORITIES = [
    ('tgn','Getty TGN'),
    ('dbp','DBpedia'),
    ('gn','Geonames'),
    ('wd','Wikidata'),
    ('spine','WHG Spine'),
    ('whg','WHG'),
]

AUTHORITY_BASEURI = {
    'align_tgn':'http://vocab.getty.edu/page/tgn/',
    'align_dbp':'http://dbpedia.org/page/',
    'align_gn':'http://www.geonames.org/',
    'align_wd':'https://www.wikidata.org/wiki/',
    'align_whg':'whg:'
}

MATCHTYPES = {
    ('exact','exactMatch'),
    ('close','closeMatch'),
    ('related','related'),
}

AREATYPES = {
    ('ccodes','Country codes'),
    ('copied','CopyPasted GeoJSON'),
    ('search','Region/Polity record'),
    ('drawn','User drawn'),
    ('predefined','World Regions'),
}
