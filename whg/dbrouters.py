from places.models import Place
from datasets.models import Dataset

class MyDBRouter(object):

    #
    def db_for_read(self, model, **hints):
        return 'whgdata' if model in (Place, Dataset) else 'default'

    def db_for_write(self, model, **hints):
        return 'whgdata' if model in (Place, Dataset) else 'default'
