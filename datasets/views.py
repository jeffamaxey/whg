# datasets.views
from django.contrib import messages
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.forms import formset_factory, modelformset_factory
from django.http import HttpResponseRedirect, JsonResponse
from django.shortcuts import render, get_object_or_404, redirect, render_to_response
from django.urls import reverse
from django.views.generic import (
  CreateView, ListView, UpdateView, DeleteView, DetailView )
from django_celery_results.models import TaskResult

import codecs, tempfile, os, re, ipdb, sys
import simplejson as json
from pprint import pprint
from areas.models import Area
from main.choices import AUTHORITY_BASEURI
from places.models import *
from datasets.forms import DatasetModelForm, HitModelForm, DatasetDetailModelForm
from datasets.models import Dataset, Hit
from datasets.static.hashes.parents import ccodes
from datasets.tasks import align_tgn, align_whg
from datasets.utils import *

def link_uri(auth,id):
  baseuri = AUTHORITY_BASEURI[auth]
  return baseuri + str(id)

# create place_name, place_geom, place_description records as req.
def augmenter(placeid, auth, tid, hitjson):
  place = get_object_or_404(Place, id=placeid)
  task = get_object_or_404(TaskResult, task_id=tid)
  kwargs=json.loads(task.task_kwargs.replace("\'", "\""))
  print('augmenter params:',type(place), auth, hitjson)
  if auth != 'align_tgn':
    return
  source = get_object_or_404(Source, src_id="getty_tgn")
  # don't add place_geom record unless flagged in task
  if 'location' in hitjson.keys() and kwargs['aug_geom'] == 'on':
    geojson=hitjson['location']
    # add geowkt and citation{id,label}
    geojson['geowkt']='POINT('+str(geojson['coordinates'][0])+' '+str(geojson['coordinates'][0])+')'
    geojson['citation']={
      "id": "tgn:"+hitjson['tgnid'],
            "label":"Getty TGN"
    }
    geom = PlaceGeom.objects.create(
      json = geojson,
            # json = hitjson['location'],
              geom_src = source,
              place_id = place,
        task_id = tid
    )
    # TODO: bulk_create??
  if len(hitjson['names']) > 0:
    for name in hitjson['names']:
        # toponym,lang,citation,when
      place_name = PlaceName.objects.create(
          toponym=name['name'] +
          ('' if name['lang'] is None else '@' + name['lang']),
          json={
              "toponym":
              name['name'] +
              ('' if name['lang'] is None else '@' + name['lang']),
              "citation": {
                  "id": "tgn:" + hitjson['tgnid'],
                  "label": "Getty TGN",
              },
          },
          place_id=place,
          task_id=tid,
      )
  if hitjson['note'] != None:
    # @id,value,lang
    descrip = PlaceDescription.objects.create(
      json = {
              "@id": 'tgn:'+hitjson['tgnid'],
                "value": hitjson['note'],
                  "lang": "en"
            },
            place_id = place,
              task_id = tid
    )

# * 
# present reconciliation hits for review, execute augmenter() for valid ones
def review(request, pk, tid, passnum): # dataset pk, celery recon task_id
  print('review() request:', request)
  ds = get_object_or_404(Dataset, id=pk)
  task = get_object_or_404(TaskResult, task_id=tid)
  # TODO: also filter by reviewed, per authority

  # filter place records by passnum for those with unreviewed hits on this task
  cnt_pass = Hit.objects.values('place_id').filter(task_id=tid, reviewed=False, query_pass=passnum).count()
  pass_int = int(passnum[4])
  passnum = passnum if cnt_pass > 0 else f'pass{str(pass_int + 1)}'
  # [place_id] for places with >0 hits
  hitplaces = Hit.objects.values('place_id').filter(
    task_id=tid,
      reviewed=False,
        query_pass=passnum)

  if len(hitplaces) > 0:
    record_list = Place.objects.order_by('title').filter(pk__in=hitplaces)
  else:
    context = {"nohits":True,'ds_id':pk,'task_id': tid, 'passnum': passnum}
    return render(request, 'datasets/review.html', context=context)
    # no unreviewed hits

  # record_list = Place.objects.order_by('title').filter(dataset=ds)
  paginator = Paginator(record_list, 1)
  page = request.GET.get('page') if request.GET.get('page') else 1
  records = paginator.get_page(page)
  count = len(record_list)

  placeid = records[0].id
  place = get_object_or_404(Place, id=placeid)

  # recon task hits
  raw_hits = Hit.objects.all().filter(place_id=placeid, task_id=tid).order_by('query_pass','-score')

  countries = [
      ccodes[0][r]['gnlabel'] + ' (' + ccodes[0][r]['tgnlabel'] + ')'
      for r in records[0].ccodes
  ]
  context = {
    'ds_id':pk, 'ds_label': ds.label, 'task_id': tid,
      'hit_list':raw_hits, 'authority': task.task_name[6:],
        'records': records, 'countries': countries, 'passnum': passnum,
        'page': page if request.method == 'GET' else str(int(page)-1)
  }

  # Hit model fields = ['task_id','authority','dataset','place_id',
  #     'query_pass','src_id','authrecord_id','json','geom' ]
  HitFormset = modelformset_factory(
    Hit, 
    fields = ('id','authority','authrecord_id','query_pass','score','json'), 
    form=HitModelForm, extra=0)
  formset = HitFormset(request.POST or None, queryset=raw_hits)
  context['formset'] = formset
  #print('context:',context)
  print('formset data:',formset.data)
  method = request.method
  if method == 'GET':
    print('a GET, just rendering next')
  else:
    try:
      if formset.is_valid():
        hits = formset.cleaned_data
        print('formset keys',formset.data.keys())
        for x in range(len(hits)):
          hit = hits[x]['id']
          if hits[x]['match'] != 'none':
            # create link 
            link = PlaceLink.objects.create(
              place_id = place,
              task_id = tid,
              # dataset = ds,
              json = {
                "type":hits[x]['match'],
                "identifier":link_uri(
                  task.task_name, hits[x]['authrecord_id'] if hits[x]['authority'] != 'whg' \
                    else hits[x]['json']['place_id']
                )
              },
              #review_note =  hits[x]['review_note'],
            )
            # update <ds>.numlinked, <ds>.total_links
            ds.numlinked = ds.numlinked +1
            ds.total_links = ds.total_links +1
            ds.save()

            # 
            # augment only for [tgn,dbp,gn,wd]
            if hits[x]['authority'] != 'whg':
              augmenter(placeid, task.task_name, tid, hits[x]['json'])
            elif hits[x]['match'] in ['exact_match','close_match']:
              print(f'index {str(placeid)} as child of ' + str(hits[x]['json']['place_id']))
            elif hits[x]['match'] == 'related':
              print('declared related - do what?')

            print('place_id',placeid,
                  'authrecord_id',hits[x]['authrecord_id'],
                  'hit.id',hit.id, type(hit.id))

          else:
            # make it a new parent unless it's been flagged
            print(f'index {str(placeid)} as a new parent')
          # TODO: 
          # set reviewed=True
          matchee = get_object_or_404(Hit, id=hit.id)
          matchee.reviewed = True
          matchee.save()
        return redirect(f'/datasets/{str(pk)}/review/{tid}/{passnum}?page={int(page)}')
      else:
        print('formset is NOT valid')
        #print('formset data:',formset.data)
        print('errors:',formset.errors)
        # ipdb.set_trace()
        # return redirect('datasets/dashboard.html', permanent=True)
    except:
      sys.exit(sys.exc_info())

  return render(request, 'datasets/review.html', context=context)


# *
# initiate, monitor align_tgn Celery task
def ds_recon(request, pk):
  ds = get_object_or_404(Dataset, id=pk)
  # TODO: handle multipolygons from "#area_load" and "#area_draw"
  me = request.user
  print('me',me,me.id)
  context = {"dataset": ds.name}

  types_ok=['ccodes','copied','drawn']
  userareas = Area.objects.all().filter(type__in=types_ok).order_by('-created')
  # TODO: this line throws an error but executes !?
  context['area_list'] = userareas if me.username == 'whgadmin' else userareas.filter(owner=me)

  predefined = Area.objects.all().filter(type='predefined').order_by('-created')
  context['region_list'] = predefined

  if request.method == 'GET':
    print('request:',request)
  elif request.method == 'POST' and request.POST:
    # what task?
    func = eval('align_'+request.POST['recon'])
    # TODO: let this vary per authority?
    region = request.POST['region'] # pre-defined UN regions
    userarea = request.POST['userarea'] # from ccodes, loaded, or drawn
    # bool options ignore for now
    #aug_names = request.POST['aug_names'] #
    #aug_notes = request.POST['aug_notes'] #
    #aug_geom = request.POST['aug_geom'] #
    bounds={
      "type":["region" if region !="0" else "userarea"],
          "id": [region if region !="0" else userarea]
    }
    print('bounds',bounds)
    # run celery/redis tasks e.g. align_tgn, align_whg
    result = func.delay(
      ds.id,
          ds=ds.id,
            dslabel=ds.label,
            owner=ds.owner.id,
        bounds=bounds
          #aug_names=aug_names,
          #aug_notes=aug_notes,
          #aug_geom=aug_geom
    )

    context['task_id'] = result.id
    context['response'] = result.state
    context['dataset id'] = ds.label
    context['authority'] = request.POST['recon']
    context['region'] = request.POST['region']
    context['userarea'] = request.POST['userarea']
    #context['aug_names'] = request.POST['aug_names']
    #context['aug_notes'] = request.POST['aug_notes']
    #context['aug_geom'] = request.POST['aug_geom']
    # context['ccodes'] = request.POST['ccodes']
    # context['hits'] = '?? not wired yet'
    context['result'] = result.get()
    #context['summary'] = result.get().summary
    pprint(locals())
    ds.status = 'recon (wip)'
    ds.save()
    return render(request, 'datasets/ds_recon.html', {'ds':ds, 'context': context})

  print('context recon GET',context)
  return render(request, 'datasets/ds_recon.html', {'ds':ds, 'context': context})

def task_delete(request,tid,scope="foo"):
  hits = Hit.objects.all().filter(task_id=tid)
  tr = get_object_or_404(TaskResult, task_id=tid)
  ds = tr.task_args[1:-1]

  # in any case, reviewed=false for hits; clear match records
  for h in hits:
    h.reviewed = False
    h.save()
  placelinks = PlaceLink.objects.all().filter(task_id=tid)
  placegeoms = PlaceGeom.objects.all().filter(task_id=tid)
  placenames = PlaceName.objects.all().filter(task_id=tid)
  placedescriptions = PlaceDescription.objects.all().filter(task_id=tid)

  placelinks.delete()
  placegeoms.delete()
  placenames.delete()
  placedescriptions.delete()

  # zap task record & its hits
  if scope == 'task':
    tr.delete()
    hits.delete()

  return redirect(f'/datasets/{ds}/detail')


# better table for viewing datasets
def drf_table(request, label, f):
  # need only for title; calls API w/javascript for data
  ds = get_object_or_404(Dataset, label=label)
  filt = f
  return render(request, 'datasets/drf_table.html', {'ds':ds,'filter':filt})

def ds_list(request, label):
  # fetch places in specified dataset
  print('in ds_list() for',label)
  qs = Place.objects.all().filter(dataset=label)
  geoms=[]
  for p in qs.all():
    feat={"type":"Feature",
          "properties":{"src_id":p.src_id,"name":p.title},
              "geometry":p.geoms.first().json}
    geoms.append(feat)
  return JsonResponse(geoms,safe=False)

# insert lpf into database
def ds_insert_lpf(request, pk):
  import os,codecs,json
  ds = get_object_or_404(Dataset, id=pk)
  [countrows,countlinked]= [0,0]
  infile = ds.file.open(mode="r")
  with ds.file:
    ds.file.open('rU')
    for row in ds.file:
      objs = {"PlaceNames":[], "PlaceTypes":[], "PlaceGeoms":[], "PlaceWhens":[],
              "PlaceLinks":[], "PlaceRelated":[], "PlaceDescriptions":[],
                "PlaceDepictions":[]}      
      countrows += 1
      jrow=json.loads(row)
      print(jrow['@id'],jrow['properties']['title'],jrow.keys())
      # TODO: get src_id into LP format

      # start Place record & save to get id
      # Place: src_id, title, ccodes, dataset
      newpl = Place(
        src_id=jrow['@id'][-8:], #TODO: add src_id to properties in LP format
        dataset=ds,
        title=jrow['properties']['title'],
        ccodes=jrow['properties']['ccodes']
      )
      newpl.save() 

      # PlaceName: place_id,src_id,toponym,task_id,json:{toponym, lang,citation,when{}}
      for n in jrow['names']:
        print('from jrow[names]:',n)
        objs['PlaceNames'].append(PlaceName(
          place_id=newpl,
          src_id=newpl.src_id,
          toponym=n['toponym'],
          json=n,
          task_id='initial'
        ))

      # PlaceType: place_id,src_id,task_id,json:{identifier,label,src_label}
      if 'types' in jrow.keys():
        for t in jrow['types']:
          #print('from jrow[types]:',t)
          objs['PlaceTypes'].append(PlaceType(
            place_id=newpl,
            src_id=newpl.src_id,
            json=t
          ))    

      # PlaceWhen: place_id,src_id,task_id,minmax,json:{timespans[],periods[],label,duration}
      if 'whens' in jrow.keys():
        for w in jrow['whens']:
          objs['PlaceWhens'].append(PlaceWhen(
            place_id=newpl,src_id=newpl.src_id,json=w))    

      # PlaceGeom: place_id,src_id,task_id,json:{type,coordinates[],when{},geo_wkt,src}
      if 'geometry' in jrow.keys():
        for g in jrow['geometry']['geometries']:
          #print('from jrow[geometry]:',g)
          objs['PlaceGeoms'].append(PlaceGeom(
            place_id=newpl,src_id=newpl.src_id,json=g))    

      # PlaceLink: place_id,src_id,task_id,json:{type,identifier}
      if 'links' in jrow.keys():
        for l in jrow['links']:
          if len(jrow['links'])>0: countlinked +=1
          objs['PlaceLinks'].append(PlaceLink(
            place_id=newpl,src_id=newpl.src_id,json=l,task_id='initial'))    

      # PlaceRelated: place_id,src_id,task_id,json{relationType,relationTo,label,when{}}
      if 'relations' in jrow.keys():
        for r in jrow['relations']:
          objs['PlaceRelated'].append(PlaceRelated(
            place_id=newpl,src_id=newpl.src_id,json=r))    

      # PlaceDescription: place_id,src_id,task_id,json:{@id,value,lang}
      if 'descriptions' in jrow.keys():
        for des in jrow['descriptions']:
          objs['PlaceDescriptions'].append(PlaceDescription(
            place_id=newpl,src_id=newpl.src_id,json=des))    

      # PlaceDepiction: place_id,src_id,task_id,json{@id,title,license}
      if 'depictions' in jrow.keys():
        for dep in jrow['depictions']:
          objs['PlaceDepictions'].append(PlaceDepiction(
            place_id=newpl,src_id=newpl.src_id,json=dep))    

      print("objs['PlaceNames']",objs['PlaceNames'])
      PlaceName.objects.bulk_create(objs['PlaceNames'])
      PlaceType.objects.bulk_create(objs['PlaceTypes'])
      PlaceWhen.objects.bulk_create(objs['PlaceWhens'])
      PlaceGeom.objects.bulk_create(objs['PlaceGeoms'])
      PlaceLink.objects.bulk_create(objs['PlaceLinks'])
      PlaceRelated.objects.bulk_create(objs['PlaceRelated'])
      PlaceDescription.objects.bulk_create(objs['PlaceDescriptions'])
      PlaceDepiction.objects.bulk_create(objs['PlaceDepictions'])

      # write some summary attributes
      ds.numrows = countrows
      ds.numlinked = countlinked
      ds.total_links = len(objs['PlaceLinks'])
      ds.status = 'in_database'
      ds.save()

    print('record:', ds.__dict__)
    ds.file.close()   

  print(f'{str(countrows)} processed')
  messages.add_message(request, messages.INFO,
                       f'inserted lpf for {str(countrows)} places')
  return redirect('/dashboard')
  
# insert LP-csv file to database
# TODO: require, handle sources
def ds_insert_csv(request, pk):
  # retrieve just-added file, insert to db
  import os, csv, codecs,json
  dataset = get_object_or_404(Dataset, id=pk)
  context = {'status': 'inserting'} #??

  infile = dataset.file.open(mode="r")
  print('ds_insert_csv(); request.GET; infile',request.GET,infile)
  # should already know delimiter
  dialect = csv.Sniffer().sniff(infile.read(16000),['\t',';','|'])
  reader = csv.reader(infile, dialect)
  infile.seek(0)
  header = next(reader, None)
  print('header', header)

  objs = {"PlaceName":[], "PlaceType":[], "PlaceGeom":[], "PlaceWhen":[],
          "PlaceLink":[], "PlaceRelated":[], "PlaceDescription":[],
            "PlaceDepiction":[]}

  # CSV * = req; ^ = desired
  # lists are ';' delimited, no brackets
  # id*, title*, name_src*, type^, variants[], parent^, ccodes[]^, lon^, lat^,
  # geom_src, close_match[]^, exact_match[]^, description, depiction

  # TODO: what if simultaneous inserts?
  countrows=0
  countlinked = 0
  countlinks = 0
  for r in reader:
  #for i, r in zip(range(100), reader):
    # TODO: should columns be required even if blank?
    # required
    #print('r',r)
    src_id = r[header.index('id')]
    title = r[header.index('title')]
    # for PlaceName insertion, strip anything in parens
    name = re.sub(' \(.*?\)', '', title)
    name_src = r[header.index('name_src')]
    if 'variants' in header:
      v = r[header.index('variants')].split(';') 
      variants = v if '' not in v else []
    else:
      variants = []
    # encouraged for reconciliation
    src_type = r[header.index('type')] if 'type' in header else 'not specified'
    aat_types = r[header.index('aat_types')].split(';') \
      if 'aat_types' in header else ''
    parent = r[header.index('parent')] if 'parent' in header else ''
    #standardize on ';' for name and ccode arrays in tab-delimited files
    ccodes = r[header.index('ccodes')].split(';') \
      if 'ccodes' in header else []
    coords = [
      float(r[header.index('lon')]),
          float(r[header.index('lat')]) ] if 'lon' in header else []
    close_matches = r[header.index('close_matches')].split(';') \
      if 'close_matches' in header else []
    exact_matches = r[header.index('exact_matches')].split(';') \
      if 'exact_matches' in header else []
    # nice to have
    minmax = [
      r[header.index('min')],
          r[header.index('max')] ] if 'min' in header else []
    description = r[header.index('description')] \
      if 'description' in header else []
    depiction = r[header.index('depiction')] \
      if 'depiction' in header else []

    #print('types (src_, aat_)',src_type,aat_types)
    # build and save Place object
    newpl = Place(
      # placeid = nextpid,
      src_id = src_id,
      dataset = dataset,
      title = title,
      ccodes = ccodes
    )
    newpl.save()
    countrows += 1
    # build associated objects and add to arrays

    # PlaceName()
    objs['PlaceName'].append(PlaceName(place_id=newpl,src_id = src_id,
          toponym = name,
          # TODO get citation label through name_src FK; here?
          json={"toponym": name, "citation": {"id":name_src,"label":""}}
    ))

    # variants if any
    if len(variants) > 0:
      for v in variants:
        objs['PlaceName'].append(PlaceName(place_id=newpl,src_id = src_id,
          toponym = v,
          json={"toponym": v, "citation": {"id":name_src,"label":""}}
        ))

    # PlaceTypes()
    if len(aat_types) > 0 and aat_types[0] !='':
      print('aat_types',aat_types)
      for t in aat_types:
        objs['PlaceType'].append(
          PlaceType(place_id=newpl,src_id = src_id,
            json={"identifier":"aat:"+t, "src_label":src_type, 
                          "label":aat_lookup(int(t))}
        ))

    # PlaceGeom()
    # TODO: test geometry type or force geojson
    if 'lon' in header and (coords[0] != 0 and coords[1] != 0):
      objs['PlaceGeom'].append(PlaceGeom(place_id=newpl,src_id = src_id,
        json={"type": "Point", "coordinates": coords,
                    "geowkt": 'POINT('+str(coords[0])+' '+str(coords[1])+')'}
      ))
    elif 'geowkt' in header:
      objs['PlaceGeom'].append(PlaceGeom(place_id=newpl,src_id = src_id,
        json=parse_wkt(r[header.index('geowkt')])
      ))            

    # PlaceLink() - close
    if len(list(filter(None,close_matches))) > 0:
      countlinked += 1
      for m in close_matches:
        countlinks += 1
        objs['PlaceLink'].append(PlaceLink(place_id=newpl,src_id = src_id,
          json={"type":"closeMatch", "identifier":m}
        ))

    # PlaceLink() - exact
    if len(list(filter(None,exact_matches))) > 0:
      countlinked += 1
      for m in exact_matches:
        countlinks += 1
        objs['PlaceLink'].append(PlaceLink(place_id=newpl,src_id = src_id,
          json={"type":"exactMatch", "identifier":m}
        ))

    # PlaceRelated()
    if 'parent' in header and parent !='':
      objs['PlaceRelated'].append(PlaceRelated(place_id=newpl,src_id = src_id,
        json={"relation_type": "gvp:broaderPartitive",
              "relation_to": "",
              "label": parent}
      ))

    # PlaceWhen()
    # timespans[{start{}, end{}}], periods[{name,id}], label, duration
    if 'min' in header:
      objs['PlaceWhen'].append(PlaceWhen(place_id=newpl,src_id = src_id,
        json={
                "timespans": [{"start":{"earliest":minmax[0]}, "end":{"latest":minmax[1]}}]
              }
      ))

    #
    # # PlaceDescription()
    # objs['PlaceDescription'].append(PlaceDescription())
    #
    # # PlaceDepiction()
    # objs['PlaceDepiction'].append(PlaceDepiction())

    # print('new place:', newpl)

  # bulk_create(Class, batchsize=n) for each
  print("objs['PlaceName']",objs['PlaceName'])  
  PlaceName.objects.bulk_create(objs['PlaceName'])
  PlaceType.objects.bulk_create(objs['PlaceType'])
  PlaceGeom.objects.bulk_create(objs['PlaceGeom'])
  PlaceWhen.objects.bulk_create(objs['PlaceWhen'])
  PlaceLink.objects.bulk_create(objs['PlaceLink'])
  PlaceRelated.objects.bulk_create(objs['PlaceRelated'])

  context['status'] = 'in_database'
  print('rows,linked,links:',countrows,countlinked,countlinks)
  dataset.numrows = countrows
  dataset.numlinked = countlinked
  dataset.total_links = countlinks
  dataset.header = header
  dataset.status = 'in_database'
  dataset.save()
  print('record:', dataset.__dict__)
  print('context from ds_insert_csv():',context)
  infile.close()
  # dataset.file.close()

  #return render(request, 'datasets/ds_recon.html', {'ds':ds, 'context': context})
  #return render(request, '/datasets/dashboard.html', {'context': context})
  return redirect('/dashboard', context=context)


# list user datasets, area, place collections
class DashboardView(ListView):
  context_object_name = 'dataset_list'
  template_name = 'datasets/dashboard.html'

  def get_queryset(self):
    # TODO: make .team() a method on User
    me = self.request.user
    if me.username == 'whgadmin':
      return Dataset.objects.all().order_by('id')
    else:
      return Dataset.objects.filter(owner__in=myteam(me)).order_by('id')


  def get_context_data(self, *args, **kwargs):
    teamtasks=[]
    me = self.request.user
    context = super(DashboardView, self).get_context_data(*args, **kwargs)

    types_ok=['ccodes','copied','drawn']
    # list areas
    userareas = Area.objects.all().filter(type__in=types_ok).order_by('-created')
    context['area_list'] = userareas if me.username == 'whgadmin' else userareas.filter(owner=self.request.user)

    # list team tasks
    if me.username == 'whgadmin':
      context['review_list'] = TaskResult.objects.filter(status='SUCCESS').order_by('-date_done')
    else:
      for t in TaskResult.objects.filter(status='SUCCESS'):
        tj=json.loads(t.task_kwargs.replace("\'", "\""))
        u=get_object_or_404(User,id=tj['owner'])
        print('args,task owner',tj,u)
        if u in myteam(me):
          teamtasks.append(t.task_id)
      context['review_list'] = TaskResult.objects.filter(task_id__in=teamtasks).order_by('-date_done')

    # status >= 'in_database'
    context['viewable'] = ['in_database','recon (wip)','recon (compl)','submitted','indexed']

    # TODO: user place collections
    #print('DashboardView context:', context)
    return context


# upload file, verify format
class DatasetCreateView(CreateView):
  form_class = DatasetModelForm
  template_name = 'datasets/dataset_create.html'
  queryset = Dataset.objects.all()
  def form_valid(self, form):
    context={}
    if form.is_valid():
      print('form is valid')
      format = form.cleaned_data['format']
      #print('cleaned_data: before ->', form.cleaned_data)

      # open & write tempf to a temp location;
      # call it tempfn for reference
      tempf, tempfn = tempfile.mkstemp()
      try:
        for chunk in form.cleaned_data['file'].chunks():
          os.write(tempf, chunk)
      except:
        raise Exception("Problem with the input file %s" % request.FILES['file'])
      finally:
        os.close(tempf)
      # open the temp file
      fin = codecs.open(tempfn, 'r', 'utf8')
      print('fin from DatasetCreateView()',fin)
      # send for format validation
      if format == 'delimited':
        result = validate_csv(fin,form.cleaned_data['owner'])
      elif format == 'lpf':
        result = validate_lpf(fin,form.cleaned_data['owner'])
      # print('cleaned_data',form.cleaned_data)
      fin.close()

      # add status & stats
      if len(result['errors']) == 0:
        print('cleaned_data:after ->',form.cleaned_data)
        #print('columns, type', result['columns'], type(result['columns']))
        obj = form.save(commit=False)
        obj.status = 'format_ok'
        obj.format = result['format']
        obj.delimiter = result['delimiter'] if "delimiter" in result.keys() else "n/a"
        obj.numrows = result['count']
        obj.header = result['columns'] if "columns" in result.keys() else []
        obj.save()
      else:
        context['status'] = 'format_error'
        print('result:', result)

    else:
      print('form not valid', form.errors)
      context['errors'] = form.errors
    return super().form_valid(form)

  def get_context_data(self, *args, **kwargs):
    context = super(DatasetCreateView, self).get_context_data(*args, **kwargs)
    context['action'] = 'create'
    return context


# detail
class DatasetDetailView(UpdateView):
  form_class = DatasetDetailModelForm
  template_name = 'datasets/dataset_detail.html'

  def get_success_url(self):
    id_ = self.kwargs.get("id")
    return '/datasets/'+str(id_)+'/detail'

  def form_valid(self, form):
    context={}
    if form.is_valid():
      print('form is valid')
      print('cleaned_data: before ->', form.cleaned_data)
    else:
      print('form not valid', form.errors)
      context['errors'] = form.errors
    return super().form_valid(form)

  def get_object(self):
    print('kwargs:',self.kwargs)
    id_ = self.kwargs.get("id")
    return get_object_or_404(Dataset, id=id_)

  def get_context_data(self, *args, **kwargs):
    context = super(DatasetDetailView, self).get_context_data(*args, **kwargs)
    id_ = self.kwargs.get("id")
    ds = get_object_or_404(Dataset, id=id_)
    bounds = self.kwargs.get("bounds")
    # print('ds',ds.label)
    context['status'] = ds.status
    placeset = Place.objects.filter(dataset=ds.label)
    context['tasks'] = TaskResult.objects.all().filter(task_args = [id_],status='SUCCESS')
    # context['tasks'] = TaskResult.objects.all().filter(task_args = [id_])
    # initial (non-task)
    context['num_links'] = PlaceLink.objects.filter(
      place_id_id__in = placeset, task_id = None).count()
    context['num_names'] = PlaceName.objects.filter(
      place_id_id__in = placeset, task_id = None).count()
    context['num_geoms'] = PlaceGeom.objects.filter(
      place_id_id__in = placeset, task_id = None).count()
    context['num_descriptions'] = PlaceDescription.objects.filter(
      place_id_id__in = placeset, task_id = None).count()
    # others
    context['num_types'] = PlaceType.objects.filter(
      place_id_id__in = placeset).count()
    context['num_when'] = PlaceWhen.objects.filter(
      place_id_id__in = placeset).count()
    context['num_related'] = PlaceRelated.objects.filter(
      place_id_id__in = placeset).count()
    context['num_depictions'] = PlaceDepiction.objects.filter(
      place_id_id__in = placeset).count()

    # augmentations (has task_id)
    context['links_added'] = PlaceLink.objects.filter(
      place_id_id__in = placeset, task_id__contains = '-').count()
    context['names_added'] = PlaceName.objects.filter(
      place_id_id__in = placeset, task_id__contains = '-').count()
    context['geoms_added'] = PlaceGeom.objects.filter(
      place_id_id__in = placeset, task_id__contains = '-').count()
    context['descriptions_added'] = PlaceDescription.objects.filter(
      place_id_id__in = placeset, task_id__contains = '-').count()

    return context


# confirm ok on delete
class DatasetDeleteView(DeleteView):
  template_name = 'datasets/dataset_delete.html'

  def get_object(self):
    id_ = self.kwargs.get("id")
    return get_object_or_404(Dataset, id=id_)

  def get_success_url(self):
    return reverse('dashboard')
