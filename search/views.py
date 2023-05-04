# various search.views
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.views.generic import View
import simplejson as json, sys
from areas.models import Area
from datasets.tasks import normalize

from elasticsearch import Elasticsearch

def fetchArea(request):
  aid = request.GET.get('pk')
  area = Area.objects.filter(id=aid)
  return JsonResponse(area)

def makeGeom(pid,geom):
  # TODO: account for non-point
  geomset = []
  if len(geom) > 0:  
    geomset.extend({
        "type": g['location']['type'],
        "coordinates": g['location']['coordinates'],
        "properties": {
            "pid": pid
        },
    } for g in geom)
  return geomset

# make stuff available in autocomplete dropdown
def suggestionItem(s):
  #print('sug geom',s['geometries'])
  print('sug', s)
  return {
      "name": s['title'],
      "type": s['types'][0]['label'],
      "whg_id": s['whg_id'],
      "pid": s['place_id'],
      "variants": [n for n in s['suggest']['input'] if n != s['title']],
      "dataset": s['dataset'],
      "ccodes": s['ccodes'],
      "geom": makeGeom(s['place_id'], s['geoms']),
  }

def nameSuggest(idx,doctype,q_initial):
  # return only parents; children will be retrieved in portal page
  # TODO: return child IDs, geometries?
  es = Elasticsearch([{'host': 'localhost', 'port': 9200}])
  suggestions = []
  res = es.search(index=idx, doc_type=doctype, body=q_initial)
  hits = res['suggest']['suggest'][0]['options']

  if len(hits) > 0:
    for h in hits:
      hit_id = h['_id']
      if 'parent' not in h['_source']['relation'].keys():
        # it's a parent, add to suggestions[]
        suggestions.append(h['_source'])

  return suggestions

class NameSuggestView(View):
  """ Returns place name suggestions """
  @staticmethod
  def get(request):
    print('in NameSuggestView',request.GET)
    """
        args in request.GET:
            [string] idx: index to be queried
            [string] search: chars to be queried for the suggest field search
            [string] doc_type: context needed to filter suggestion searches
        """
    idx = request.GET.get('idx')
    text = request.GET.get('search')
    doctype = request.GET.get('doc_type')
    q_initial = { 
      "suggest":{"suggest":{"prefix":text,"completion":{"field":"suggest"}}}
    }
    suggestions = nameSuggest(idx, doctype, q_initial)
    suggestions = [ suggestionItem(s) for s in suggestions]
    return JsonResponse(suggestions, safe=False)  

## ***
##    get features in current map viewport
## ***
def contextSearch(idx,doctype,q):
  print('context query',q)
  es = Elasticsearch([{'host': 'localhost', 'port': 9200}])
  count_hits=0
  result_obj = {"hits":[]}
  res = es.search(index=idx, doc_type=doctype, body=q, size=300)
  hits = res['hits']['hits']
  # TODO: refactor this bit
  if len(hits) > 0:
    for hit in hits:
      count_hits +=1
      if idx=="whg":
        result_obj["hits"].append(normalize(hit["_source"],'whg'))
      else:
        result_obj["hits"].append(hit["_source"]['body'])
  result_obj["count"] = count_hits
  return result_obj
def traceGeoSearch(idx,doctype,q):
  es = Elasticsearch([{'host': 'localhost', 'port': 9200}])
  #try:
  res = es.search(index='whg', doc_type='place', body=q, size=300)
  #except:
    #print(sys.exc_info()[0])
  hits = res['hits']['hits']
  #geoms=[]
  collection={"type":"FeatureCollection","features":[]}
  for h in hits:
    if len(h['_source']['geoms'])>0:
      collection['features'].append(
        {"type":"Feature",
         "geometry":h['_source']['geoms'][0]['location'],
         "properties":{"title":h['_source']['title'],"whg_id":h['_source']['whg_id']}}
      )
  print(str(len(collection['features']))+' features')  
  return collection

class FeatureContextView(View):
  """ Returns places in a bounding box """
  @staticmethod
  def get(request):
    print('FeatureContextView GET:',request.GET)
    """
    args in request.GET:
        [string] idx: index to be queried
        [string] search: geometry to intersect
        [string] doc_type: 'place' in this case
    """
    idx = request.GET.get('idx')
    bbox = request.GET.get('search')
    doctype = request.GET.get('doc_type')
    q_context_all = {"query": { 
      "bool": {
        "must": [{"match_all":{}}],
        "filter": { "geo_shape": {
          "geoms.location": {
            "shape": {
              "type": "polygon",
              "coordinates": json.loads(bbox)
            },
            "relation": "within"
          }
        }}        
      }    
    }}
    features = contextSearch(idx, doctype, q_context_all)
    return JsonResponse(features, safe=False)

class TraceGeomView(View):
  """ Returns places in a trace body """
  @staticmethod
  def get(request):
    print('TraceGeomView GET:',request.GET)
    """
    args in request.GET:
        [string] idx: index to be queried
        [string] search: whg_id
        [string] doc_type: 'tracw' in this case
    """
    idx = request.GET.get('idx')
    trace_id = request.GET.get('search')
    doctype = request.GET.get('doc_type')
    q_trace = {"query": {"bool": {"must": [{"match":{"_id": trace_id}}]}}}
    bodies = contextSearch(idx, doctype, q_trace)['hits'][0]
    bodyids = [b['whg_id'] for b in bodies if b['whg_id']]
    q_geom={"query": {"bool": {"must": [{"terms":{"_id": bodyids}}]}}}
    geoms = traceGeoSearch(idx,doctype,q_geom)
    return JsonResponse(geoms, safe=False)      

def home(request):
  return render(request, 'search/home.html')

def advanced(request):
  print('in search/advanced() view')
  return render(request, 'search/advanced.html')

