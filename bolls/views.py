import re
import os
import ast
# import math
import unicodedata
import json
from django.db.models import Count, Q
from django.contrib.postgres.search import SearchQuery, SearchRank, SearchVector, TrigramSimilarity, TrigramWordSimilarity
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.hashers import is_password_usable
from django.contrib.auth.models import User
from django.contrib.auth import login, authenticate
from django.contrib.messages import get_messages
from django.shortcuts import render, redirect
from django.template import RequestContext
from django.http import JsonResponse, HttpResponse

from bolls.books_map import *
from bolls.forms import SignUpForm

from .models import Verses, Bookmarks, History, Note, Commentary, Dictionary

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


bolls_index = 'bolls/index.html'


def index(request):
    if request.user.is_authenticated:
        print(request.user.id)
    return render(request, bolls_index)


def cross_origin(response):
    response["Access-Control-Allow-Origin"] = "*"
    response["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    response["Access-Control-Max-Age"] = "1000"
    response["Access-Control-Allow-Headers"] = "X-Requested-With, Content-Type"
    return response


def getTranslation(request, translation):
    all_verses = Verses.objects.filter(
        translation=translation).order_by('book', 'chapter', 'verse')
    all_commentaries = Commentary.objects.filter(
        translation=translation).order_by('book', 'chapter', 'verse')

    def serializeVerse(obj):
        verse = {
            "pk": obj.pk,
            "translation": obj.translation,
            "book": obj.book,
            "chapter": obj.chapter,
            "verse": obj.verse,
            "text": obj.text
        }
        comment = ''
        for item in all_commentaries:
            if item.verse == obj.verse and item.chapter == obj.chapter and item.book == obj.book:
                if len(comment) > 0:
                    comment = "%s<br>" % (comment)
                comment = "%s%s" % (comment, item.text)

        if len(comment) > 0:
            verse["comment"] = comment
        return(verse)

    verses = [serializeVerse(obj) for obj in all_verses]
    return cross_origin(JsonResponse(verses, safe=False))


def getChapter(translation, book, chapter):
    all_objects = Verses.objects.filter(
        book=book, chapter=chapter, translation=translation).order_by('verse')
    d = []
    for obj in all_objects:
        d.append({
            "pk": obj.pk,
            "verse": obj.verse,
            "text": obj.text
        })
    return d


def getText(request, translation, book, chapter):
    return cross_origin(JsonResponse(getChapter(translation, book, chapter), safe=False))


def getChapterWithCommentaries(translation, book, chapter):
    all_verses = Verses.objects.filter(
        book=book, chapter=chapter, translation=translation).order_by('verse')

    all_commentaries = Commentary.objects.filter(
        book=book, chapter=chapter, translation=translation).order_by('verse')

    d = []
    for obj in all_verses:
        verse = {
            "pk": obj.pk,
            "verse": obj.verse,
            "text": obj.text
        }
        comment = ''
        for item in all_commentaries:
            if item.verse == obj.verse:
                if len(comment) > 0:
                    comment += '<br>'
                comment += item.text
        if len(comment) > 0:
            verse["comment"] = comment
        d.append(verse)
    return d


def getChapterWithComments(request, translation, book, chapter):
    return cross_origin(JsonResponse(getChapterWithCommentaries(translation, book, chapter), safe=False))


def search(request, translation, piece=''):
    if len(piece) == 0:
        piece = request.GET.get('search', '')
    match_case = request.GET.get('match_case', '') == 'true'
    match_whole = request.GET.get('match_whole', '') == 'true'

    d = []
    piece = piece.strip()

    if len(piece) > 2:
        results_of_search = []
        if match_whole:
            if match_case:
                results_of_search = Verses.objects.filter(
                    translation=translation, text__contains=piece).order_by('book', 'chapter', 'verse')
            else:
                results_of_search = Verses.objects.filter(
                    translation=translation, text__icontains=piece).order_by('book', 'chapter', 'verse')
        else:
            query_set = []

            for word in piece.split():
                if match_case:
                    query_set.append(
                        "Q(translation=\"" + translation + "\", text__contains=" + json.dumps(word) + ")")
                else:
                    query_set.append(
                        "Q(translation=\"" + translation + "\", text__icontains=" + json.dumps(word) + ")")

            query = ' & '.join(query_set)

            results_of_exec_search = Verses.objects.filter(
                eval(query)).order_by('book', 'chapter', 'verse')

            if len(results_of_exec_search) < 24:
                vector = SearchVector('text')
                query = SearchQuery(piece)
                results_of_rank = Verses.objects.annotate(rank=SearchRank(
                    vector, query)).filter(translation=translation, rank__gt=(0.05)).order_by('-rank')

                results_of_search = []
                if len(results_of_rank) < 24:
                    results_of_similarity = Verses.objects.annotate(rank=TrigramWordSimilarity(
                        piece, 'text')).filter(translation=translation, rank__gt=0.5).order_by('-rank')

                    results_of_search = list(results_of_similarity) + \
                        list(set(results_of_rank) - set(results_of_similarity))

                results_of_search.sort(
                    key=lambda verse: verse.rank, reverse=True)

                if len(results_of_exec_search) > 0:
                    results_of_search = list(results_of_exec_search) + \
                        list(set(results_of_search) -
                             set(results_of_exec_search))
            else:
                results_of_search = results_of_exec_search

        def highlightHeadline(text):
            highlighted_text = text
            mark_replacement = re.compile(re.escape(piece), re.IGNORECASE)
            highlighted_text = mark_replacement.sub(
                "<mark>" + piece + "</mark>", highlighted_text)
            if not match_whole:
                for word in piece.split():
                    mark_replacement = re.compile(
                        re.escape(word), re.IGNORECASE)
                    highlighted_text = mark_replacement.sub(
                        "<mark>" + word + "</mark>", highlighted_text)
            return highlighted_text

        for obj in results_of_search[0:1024]:
            d.append({
                "pk": obj.pk,
                "translation": obj.translation,
                "book": obj.book,
                "chapter": obj.chapter,
                "verse": obj.verse,
                "text": highlightHeadline(obj.text)
            })
    else:
        d = [{"readme": "Your query is not longer than 2 characters! And don't forget to trim it)"}]
    return cross_origin(JsonResponse(d, safe=False))


def cleanhtml(raw_html):
    cleanr = re.compile('<.*?>|&([a-z0-9]+|#[0-9]{1,6}|#x[0-9a-f]{1,6});')
    cleantext = re.sub(cleanr, '', raw_html)
    return cleantext


def getDescription(verses, verse, endverse):
    if verse <= len(verses) and len(verses) > 0:
        i = 0
        description = verses[verse - 1]['text']
        if endverse > 0 and endverse - verse != 0:
            for i in range(verse, endverse):
                if i < len(verses):
                    description += ' ' + verses[i]['text']
        return cleanhtml(description)
    else:
        return 'Corrupted link!'


def linkToVerse(request, translation, book, chapter, verse):
    verses = getChapterWithCommentaries(translation, book, chapter)
    return render(request, bolls_index, {"translation": translation, "book": book, "chapter": chapter, "verse": verse, "verses": verses, "description": getDescription(verses, verse, 0)})


def linkToVerses(request, translation, book, chapter, verse, endverse):
    verses = getChapterWithCommentaries(translation, book, chapter)
    return render(request, bolls_index, {"translation": translation, "book": book, "chapter": chapter, "verse": verse, "endverse": endverse, "verses": verses, "description": getDescription(verses, verse, endverse)})


def linkToChapter(request, translation, book, chapter):
    verses = getChapterWithCommentaries(translation, book, chapter)
    return render(request, bolls_index, {"translation": translation, "book": book, "chapter": chapter, "verses": verses, "description": getDescription(verses, 1, 3)})


def signUp(request):
    if request.method == 'POST':
        form = SignUpForm(request.POST)
        if form.is_valid():
            form.save()
            username = form.cleaned_data.get('username')
            raw_password = form.cleaned_data.get('password1')
            user = authenticate(username=username, password=raw_password)
            login(request, user)
            return redirect('index')
    else:
        form = SignUpForm()
    return render(request, 'registration/signup.html', {'form': form})


def deleteAccount(request):
    message = ''
    if request.user.is_authenticated:
        try:
            request.user.delete()
            message = "account_deleted"

        except Exception as e:
            return render(request, bolls_index, {'message': e.message})
    print(message)
    return render(request, bolls_index, {"message": message})


def editAccount(request):
    if request.method == 'POST':
        received_json_data = json.loads(request.body)
        newusername = received_json_data["newusername"]
        newname = newname = received_json_data.get("newname", '')
        if User.objects.filter(username=newusername).exists():
            if request.user.username != newusername:
                return HttpResponse(status=409)
        user = request.user
        user.username = newusername
        user.first_name = newname
        user.save()
        return HttpResponse(status=200)
    else:
        return HttpResponse(status=405)


def getBookmarks(request, translation, book, chapter):
    if request.user.is_authenticated:
        all_objects = Verses.objects.filter(
            book=book, chapter=chapter, translation=translation).order_by('verse')
        bookmarks = []
        for obj in all_objects:
            for bookmark in obj.bookmarks_set.all():
                note = ''
                if bookmark.note is not None:
                    note = bookmark.note.text
                bookmarks.append({
                    "verse": bookmark.verse.pk,
                    "date": bookmark.date,
                    "color": bookmark.color,
                    "collection": bookmark.collection,
                    "note": note,
                })
        return JsonResponse(bookmarks, safe=False)
    else:
        return JsonResponse([], safe=False)


def mapBookmarks(bookmarkslist):
    bookmarks = []
    for bookmark in bookmarkslist:
        note = ''
        if bookmark.note is not None:
            note = bookmark.note.text
        bookmarks.append({
            "verse": {
                "pk": bookmark.verse.pk,
                "translation": bookmark.verse.translation,
                "book": bookmark.verse.book,
                "chapter": bookmark.verse.chapter,
                "verse": bookmark.verse.verse,
                "text": bookmark.verse.text,
            },
            "date": bookmark.date,
            "color": bookmark.color,
            "collection": bookmark.collection,
            "note": note,
        })
    return bookmarks


def getProfileBookmarks(request, range_from, range_to):
    if request.user.is_authenticated:
        user = request.user
        bookmarks = mapBookmarks(user.bookmarks_set.all().order_by(
            '-date', 'verse')[range_from:range_to])
        return JsonResponse(bookmarks, safe=False)
    return JsonResponse([], safe=False)


def getSearchedProfileBookmarks(request, query, range_from, range_to):
    user = request.user
    bookmarks = mapBookmarks(user.bookmarks_set.all().filter(
        collection__icontains=query).order_by('-date', 'verse')[range_from:range_to]),
    return JsonResponse(bookmarks, safe=False)


def getBookmarksWithNotes(request, range_from, range_to):
    user = request.user
    bookmarks = mapBookmarks(user.bookmarks_set.all().filter(
        note__isnull=False).order_by('-date', 'verse')[range_from:range_to]),
    return JsonResponse(bookmarks, safe=False)


def getCategories(request):
    if request.user.is_authenticated:
        user = request.user
        all_objects = user.bookmarks_set.values('collection').annotate(
            dcount=Count('collection')).order_by('-date')
        fresh_collections = [b for b in all_objects]
        collections = []
        for collections_dict in fresh_collections:
            for collection in collections_dict['collection'].split(' | '):
                if not collection in collections and len(collection):
                    collections.append(collection)
        return JsonResponse({"data": collections}, safe=False)
    return JsonResponse({"data": []}, safe=False)


@csrf_exempt
def getParallelVerses(request):
    if request.method == 'POST':
        try:
            received_json_data = json.loads(request.body)
            if received_json_data["chapter"] > 0 and received_json_data["book"] > 0 and len(received_json_data["translations"]) > 5 and len(received_json_data["verses"]) > 2:
                book = received_json_data["book"]
                chapter = received_json_data["chapter"]
                response = []
                query_set = []
                for translation in ast.literal_eval(received_json_data["translations"]):
                    for verse in ast.literal_eval(received_json_data["verses"]):
                        query_set.append("Q(translation=\"" + translation + "\", book=" + str(
                            book) + ", chapter=" + str(chapter) + ", verse=" + str(verse) + ")")

                query = ' | '.join(query_set)
                queryres = Verses.objects.filter(eval(query))

                for translation in ast.literal_eval(received_json_data["translations"]):
                    verses = []
                    for verse in ast.literal_eval(received_json_data["verses"]):
                        v = [x for x in queryres if (
                            (x.verse == verse) & (x.translation == translation))]
                        if len(v):
                            for item in v:
                                verses.append({
                                    "pk": item.pk,
                                    "translation": item.translation,
                                    "book": item.book,
                                    "chapter": item.chapter,
                                    "verse": item.verse,
                                    "text": item.text,
                                })
                        else:
                            verses.append({
                                "translation": translation,
                            })
                    response.append(verses)
                return JsonResponse(response, safe=False)
            else:
                return HttpResponse("Body fields are incorrect", status=400)
        except:
            return HttpResponse("Body fields are incorrect", status=400)
    else:
        return HttpResponse("The request should be POSTed", status=400)


def saveBookmarks(request):
    if not request.user.is_authenticated:
        return HttpResponse(status=401)
    if request.method != 'POST':
        return HttpResponse(status=405)

    received_json_data = json.loads(request.body)
    user = request.user

    def createNewBookmark():
        note = None
        if len(received_json_data["note"]):
            note = Note.objects.create(text=received_json_data["note"])
        user.bookmarks_set.create(
            verse=verse, date=received_json_data["date"], color=received_json_data["color"], collection=received_json_data["collections"], note=note)

    for verseid in ast.literal_eval(received_json_data["verses"]):
        try:
            verse = Verses.objects.get(pk=verseid)
            # If there is an existing bookmark -- update it
            try:
                obj = user.bookmarks_set.get(user=user, verse=verse)
                obj.date = received_json_data["date"]
                obj.color = received_json_data["color"]
                obj.collection = received_json_data["collections"]
                note = obj.note
                if note is not None:
                    if len(received_json_data["note"]):
                        obj.note.text = received_json_data["note"]
                        obj.note.save()
                    else:
                        obj.note.delete()
                        obj.note = None
                else:
                    if len(received_json_data["note"]):
                        note = Note.objects.create(
                            text=received_json_data["note"])
                        obj.note = note
                        obj.note.save()
                obj.save()
            # Else create a new one
            except Bookmarks.DoesNotExist:
                createNewBookmark()
            # If there accidentsly are a few bookmarks for a single verse -- remove them all and create a new bookmark
            except Bookmarks.MultipleObjectsReturned:
                removeBookmarks(user, [verseid])
                createNewBookmark()

        except Verses.DoesNotExist:
            return HttpResponse(status=418)
    return JsonResponse({"status_code": 200}, safe=False)


def saveHistory(request):
    if request.user.is_authenticated:
        received_json_data = json.loads(request.body)
        user = request.user
        try:
            obj = user.history_set.get(user=user)
            obj.history = received_json_data["history"]
            obj.save()
        except History.DoesNotExist:
            user.history_set.create(history=received_json_data["history"])

        except History.MultipleObjectsReturned:
            user.history_set.all().delete()
            user.history_set.create(history=received_json_data["history"])
        return JsonResponse({"response": "200"}, safe=False)
    else:
        return HttpResponse(status=405)


def deleteBookmarks(request):
    if request.user.is_authenticated:
        received_json_data = json.loads(request.body)
        removeBookmarks(request.user, ast.literal_eval(
            received_json_data["verses"]))
        return JsonResponse({"response": "200"}, safe=False)
    else:
        return HttpResponse(status=401)


def removeBookmarks(user, verses):
    for verseid in verses:
        verse = Verses.objects.get(pk=verseid)
        user.bookmarks_set.filter(verse=verse).delete()


def historyOf(user):
    if user.is_authenticated:
        try:
            obj = user.history_set.get(user=user)
            return obj.history
        except History.MultipleObjectsReturned:
            user.history_set.filter(user=user).delete()
            return []
        except History.DoesNotExist:
            return []
    else:
        return []


def getHistory(request):
    return JsonResponse(historyOf(request.user), safe=False)


def userLogged(request):
    if request.user.is_authenticated:
        return JsonResponse({"username": request.user.username, "name": request.user.first_name, "is_password_usable": is_password_usable(request.user.password), "history": historyOf(request.user)}, safe=False)
    return JsonResponse({"username": ""}, safe=False)


def api(request):
    return render(request, 'bolls/api.html')


def handler404(request, *args, **argv):
    response = render('404.html', {}, context_instance=RequestContext(request))
    response.status_code = 404
    return response


def handler500(request, *args, **argv):
    response = render('500.html', {}, context_instance=RequestContext(request))
    response.status_code = 500
    return response

def stripVowels(raw_string):
    # raw_string = raw_string.lower()
    res = ''
    if len(re.findall('[α-ωΑ-Ω]', raw_string)):
        nfkd_form = unicodedata.normalize('NFKD', raw_string)
        res = u"".join([c for c in nfkd_form if not unicodedata.combining(c)])

    else:
        res = re.sub(r'[\u0591-\u05C7]', '', raw_string)

        # Replace some letters, which are not present in a given unicode range, manually.
        res = res.replace('שׁ', 'ש')
        res = res.replace('שׂ', 'ש')


    res = res.replace('‎', '')
    return res

# translation `international/WLC`
def parseLinks(text, translation):
	if type(text) == float:
		return ''

	text = re.sub(r'(<[/]?span[^>]*)>', '', text)	# Clean up unneeded spans
	text = re.sub(r'( class=\'\w+\')', '', text)	# Avoid unneded classes on anchors

	pieces = text.split("'")

	result = ''
	for piece in pieces:
		if piece.startswith('B:'):
			result += "'/" + translation + '/'
			digits = re.findall(r'\d+', piece)
			try:
				result += str(books_map[(digits[0])]) + '/' + digits[1] + '/' + digits[2]
			except:
				print(piece)

			if len(digits) > 3:
				result += '-' + digits[3]
			result += "'"
		else:
			result += piece
	return result


def searchInDictionary(request, dict, query):
    unaccented_query = stripVowels(query)
    print(unaccented_query)

    # Rank search
    search_vector = SearchVector('lexeme__unaccent')
    search_query = SearchQuery(unaccented_query)
    results_of_rank = Dictionary.objects.annotate(rank=SearchRank(
        search_vector, search_query)).filter(Q(short_definition__search=query) | Q(topic=query) | Q(rank__gt=0), dictionary=dict).order_by('-rank')

    # SImilarity search
    results_of_similarity = Dictionary.objects.annotate(rank=TrigramSimilarity(
        'lexeme__unaccent', query)).filter(dictionary=dict, rank__gt=0.3).order_by('-rank')

    # Merge both kinds of search
    results_of_search = list(results_of_similarity) + list(set(results_of_rank) - set(results_of_similarity))
    results_of_search.sort(key=lambda verse: verse.rank, reverse=True)


    translation = ""
    if dict == 'RUSD':
        translation = 'international/SYNOD'
    else:
        translation = 'international/KJV'

    d = []
    for result in results_of_search:
        d.append({
            "topic": result.topic,
            "definition": parseLinks(result.definition, translation),
            "lexeme": result.lexeme,
            "transliteration": result.transliteration,
            "pronunciation": result.pronunciation,
            "short_definition": result.short_definition,
            "weight": result.rank
        })
    return JsonResponse(d, safe=False)


# def fixBookmarks(request):
#     # rename KJV to OKJC
#     # push new KJV to the db
#     # map bookmarks in given range to the new KJV

#     # bookmarks = Bookmarks.objects.all().filter(verse__gte=992272, verse__lte=1023502)
#     bookmarks = Bookmarks.objects.all()
#     length = len(bookmarks)
#     for bookmark in bookmarks:
#         if bookmark.verse.id >= 992272 and bookmark.verse.id <= 1023502:
#             print(bookmark.verse.book, bookmark.verse.chapter, bookmark.verse.verse, bookmark.verse.translation)
#             new_verse = Verses.objects.get(translation="KJV", book=bookmark.verse.book, chapter=bookmark.verse.chapter, verse=bookmark.verse.verse)
#             if new_verse:
#                 bookmark.verse = new_verse
#                 bookmark.save()
#             else:
#                 print('AAAAAAAAA')

#    return HttpResponse(length)
