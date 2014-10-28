import sys, os
import pprint
import re
import numpy
from operator import add
from pyspark.mllib.regression import LabeledPoint
from pyspark.mllib.classification import NaiveBayes
from datetime import datetime  #, time, timedelta
from time import time
from pyspark import SparkContext

use_lexicon = 0
use_hash = 1
#use_hash_signing = 1
use_log = 1
#hashtable_size = 6001
s_time = time()


def remPlural( word ):
    word = word.lower()
    if word.endswith('s'):
        return word[:-1]
    else:
        return word


def vector(tupleList,lexicon):
    #input: list of tuples [(word,count),(word,count)...]
    #return: vector representing word counts in lexicon [0,1,4,2,..]
    vector = [0]*(len(lexicon))
    for (x,y) in tupleList:
        #print ("x:",x, " y:",y, "lexicon(x): ",lexicon.index(x))
        try:
            idx  = lexicon.index(x)
        except:
            continue
        vector[idx] = y
    return vector

def sign_hash(x):
    return 1 if len(x)%2 == 1 else -1

def hashVectorSigned(tupleList,hashtable_size):
    #input: list of tuples [(word,count),(word,count)...]
    #return: hashTable
     hash_table = [0]*hashtable_size
     for (word,count)in tupleList:
         x = (hash(word) % hashtable_size) if hashtable_size else 0
         hash_table[x] = hash_table[x] + sign_hash(word) * count
     return map(lambda x:abs(x),hash_table)

def hashVectorUnsigned(tupleList,hashtable_size):
    #input: list of tuples [(word,count),(word,count)...]
    #return: hashTable
     hash_table = [0]*hashtable_size
     for (word,count)in tupleList:
         x = (hash(word) % hashtable_size) if hashtable_size else 0
         hash_table[x] = hash_table[x] + count
     return map(lambda x:abs(x),hash_table)

def hashVector(tupleList,hashtable_size,use_hash_signing):
    if use_hash_signing:
        return hashVectorSigned(tupleList,hashtable_size)
    else:
        return hashVectorUnsigned(tupleList,hashtable_size)

def wordCountPerFile(rdd):
    #input: rdd of (file,word) tuples
    #return: rdd of (file, [(word, count),(word, count)...]) tuples
    logTimeIntervalWithMsg(s_time,"##### BUILDING wordCountPerFile #####")
    rdd = rdd.map(lambda (x):((x[0],x[1]),  1))
    #print('##### GETTING THE  ((file,word),n) WORDCOUNT PER (DOC, WORD) #####')
    rdd = rdd.reduceByKey(add)
    #print('##### REARRANGE AS  (file, [(word, count)])  #####')
    rdd = rdd.map (lambda (a,b) : (a[0],[(a[1],b)]))
    #print ('##### CONCATENATE (WORD,COUNT) LIST PER FILE AS  (file, [(word, count),(word, count)...])  #####')
    rdd = rdd.reduceByKey(add)
    return rdd


def vectorise(rdd,lexicon):
    #input: rdd of (file, [(word, count),(word, count)...]) tuples
    #return: rdd of (file,[vector]) tuples
    #print('##### CREATE A DOC VECTOR AGAINST THE LEXICON   #####')
    rdd = rdd.map (lambda (f,wc): ( f,vector(wc,lexicon)))
    return rdd


def confusionMatrix (tupleList):
    mx = [0,0,0,0]
    for (x,y)in tupleList:
        mx[((x<<1) + y)] += 1
    return mx

def confusionDict (tupleList):
    mx =[0,0,0,0]
    for (x,y)in tupleList:
        mx[((x<<1) + y)] += 1
    dict = {'TN':mx[0],'FP':mx[1],'FN':mx[2],'TP':mx[3]}

    dict['TotalTrue']     = dict['TP'] + dict['FN']
    dict['TotalFalse']    = dict['TN'] + dict['FP']
    dict['TotalSamples']  = len(tupleList)
    dict['TotalPositive'] = dict['TP'] + dict['FP']
    dict['TotalNegative'] = dict['TN'] + dict['FN']
    dict['TotalCorrect']  = dict['TP'] + dict['TN']
    dict['TotalErrors']   = dict['FN'] + dict['FP']
    dict['Recall']        = float(dict['TP'])/dict['TotalTrue'] if dict['TotalTrue']>0 else 0
    dict['Precision']     = float(dict['TP'])/dict['TotalPositive'] if dict['TotalPositive']>0 else 0
    dict['Sensitivity']   = float(dict['TP'])/dict['TotalSamples'] if dict['TotalSamples']>0 else 0
    dict['Specificity']   = float(dict['TN'])/dict['TotalSamples'] if dict['TotalSamples']>0 else 0
    dict['ErrorRate']     = float(dict['TotalErrors'])/dict['TotalSamples'] if dict['TotalSamples']>0 else 0
    dict['Accuracy']      = float(dict['TotalCorrect'])/dict['TotalSamples'] if dict['TotalSamples']>0 else 0
    dict['Fmeasure']      = 2*float(dict['TP'])/(dict['TotalTrue']+dict['TotalPositive']) \
                                                    if (dict['TotalTrue']+dict['TotalPositive']>0) else 0
    dict['Fmeasure2']     = 1/((1/dict['Precision']) + (1/dict['Recall'])) \
                                                    if dict['Precision']>0 and dict['Recall']>0 else 0
    dict['Fmeasure3']     = 2*dict['Precision']*dict['Recall']/(dict['Precision']+dict['Recall']) \
                                                    if (dict['Precision']+dict['Recall']>0) else 0
    return dict

def printConfusionMatrix(confusionDict):
    print ("            condition\n" \
          "   test    T         F  \n"\
          "    T %6i    %6i    \n"\
          "    F %6i    %6i    \n"\
            % ( confusionDict['TP'], confusionDict['FP'],\
                confusionDict['FN'], confusionDict['TN']))

def printConfusionDict(confusionDict):
    print ("                  relevant       \n" \
          " retreived     yes       no  \n"\
          "   yes  %6i TP %6i FP %6i  \n"\
          "   no   %6i FN %6i TN %6i   \n"\
          "        %6i    %6i    %6i   \n"\
          % ( confusionDict['TP'], confusionDict['FP'],confusionDict['TotalPositive'],\
                confusionDict['FN'], confusionDict['TN'],confusionDict['TotalNegative'],\
                confusionDict['TotalTrue'], confusionDict['TotalFalse'], confusionDict['TotalSamples']))
    print ("                  truth       \n" \
           " prediction   spam       ham  \n"\
           "    spam %6i TP %6i FP   \n"\
           "     ham %6i FN %6i TN   \n"\
        "\n"\
        "classifier stats (classes spam and ham) \n"
        "total samples: %i \n"\
        "     accuracy: %.3f    TP+TN/total \n"
        "   error rate: %.3f    FN+FP/total \n"
        "\n"
        "class-specific stats (class spam)\n"
            "  sensitivity: %.3f   TP/total\n"\
        "  specificity: %.3f   FN/total\n"\
        "       recall: %.3f   TP/totalTrue TP/TP+TN \n"\
        "    precision: %.3f   TP/totalPos  TP/TP+FP\n"\

        "    f-measure: %.3f   2*TP/(totalTrue+totalPos) 2TP/(TP+TN+TP+FP)\n"\
        "   f-measure2: %.3f   1/(1/precision + 1/recall) \# this one looks wrong\n"\

        #http://nlp.stanford.edu/IR-book/html/htmledition/evaluation-of-unranked-retrieval-sets-1.html#10657
        "   f-measure3: %.3f   2 * precision * recall / (precision + recall)\n"\
    \
            % ( confusionDict['TP'], confusionDict['FP'],\
                confusionDict['FN'], confusionDict['TN'],\
                confusionDict['TotalSamples'],      \
                confusionDict['Accuracy'],\
                confusionDict['ErrorRate'],\
                confusionDict['Sensitivity'],\
                confusionDict['Specificity'],\
                confusionDict['Recall'],\
                confusionDict['Precision'],\

                confusionDict['Fmeasure'],\
                confusionDict['Fmeasure2'],\
                confusionDict['Fmeasure3'],\

        ))


def logTimeInterval(s_time):
    if (use_log):
        #timedelta = (datetime.now() - s_time)
        timedelta = time() - s_time

        print ("log:{:3f}".format(timedelta))

def logTimeIntervalWithMsg(s_time, msg):
    if (use_log):
        message = msg if msg else ""
        #timedelta = (datetime.now() - s_time)
        timedelta = time() - s_time
        print "log:{:.3f} {}".format(timedelta,message)

def logPrint(string):
    print string if use_log else '.',

def extractRDDs(path,validation_index,file_range):
    firstLoop =1
    for k in file_range:
        tmpPath = spamPath+'part'+str(k)
        if k==validation_index:
            testSet = sc.wholeTextFiles(tmpPath)
        else:
            tmpRDD = sc.wholeTextFiles(tmpPath)
            if (firstLoop):
                trainingSet = tmpRDD
                firstLoop = 0
            else:
                trainingSet = trainingSet.union(tmpRDD)

    return (trainingSet,testSet)


def lexiconArray(rdd):
    #input: rdd of (file,word) tuples
    #output: [word1,word2,word3] array of distinct words
    logTimeIntervalWithMsg(s_time,"##### BUILDING THE LEXICON #####")
    training_words = rdd.map (lambda(f,x):x)
    logTimeIntervalWithMsg(s_time,"training_words: %i" %  training_words.count())
    training_lexicon = training_words.distinct()
    logTimeIntervalWithMsg(s_time,"training_lexicon: %i" % training_lexicon.count())
    return training_lexicon.collect()



def processRDD(rdd,create_lexicon):
    #input: rdd as read from filesystem
    #output: array of [processed RDD,lexicon] or [processed RDD] if create_lexicon is None

    logTimeIntervalWithMsg(s_time,"##### BUILDING (file,word) tuples #####")

    processedRDD = rdd.flatMap(lambda (file,word):([(file[file.rfind("/")+1:],remPlural(word)) \
                                                   for word in re.split('\W+',word) \
                                                   if len(word)>0]))
    lexicon = lexiconArray(processedRDD) if create_lexicon else None
    processedRDD = wordCountPerFile(processedRDD)
    return [processedRDD,lexicon]



if __name__ == "__main__":

    if len(sys.argv) != 4:
        print >> sys.stderr, "Usage: spamPath <folder> testfolder <folder> stoplist<file>"
        exit(-1)
    sc = SparkContext(appName="spamFilter")
    logTimeIntervalWithMsg(s_time,"spark initialised, resetting timer")
    s_time = time()


    #1 Start by loading the files from part1 with wholeTextFiles.
    spamPath = (sys.argv[1])
    print "\nspamPath: {}\n".format(spamPath)
    validation_index = 1
    rdds = extractRDDs(spamPath,validation_index,range(1,4))
    trainingSet = rdds[0]
    testSet = rdds[1]
    #(trainingSet,testSet) = rdds

   # trainingSet = sc.wholeTextFiles(sys.argv[1], 1)
    stopfile    = sc.textFile(sys.argv[3],1)
    stoplist    = stopfile.flatMap (lambda x: re.split('\W+',x)).collect()


    trainingArray = processRDD(trainingSet,use_lexicon)
    trainingSet =trainingArray[0]
    if use_lexicon: lexicon = trainingArray[1]
    testSet = processRDD(testSet,None)[0]

print "\n"
use_hash_signing = 1
use_log = 0
print("hSize\tsigned?\tTP\tFP\tFN\tTN\tRecall\tPrcsion\tF-mesr\tAccuracy")
for hashtable_size in range (1,100,1):
#if 1:
        #hashtable_size = 8000


        #train6 = train5.map (lambda (f,x): ( f,vector(x,lexicon)))

        if use_hash:
            logTimeIntervalWithMsg(s_time,'##### CREATE A DOC VECTOR OF HASHES  #####')
            hashtrain6 = trainingSet.map(lambda(f,x):(f,hashVector(x,hashtable_size,use_hash_signing)))
            #print ("hashtrain6 sample:", hashtrain6.takeSample(True,4,0))
            hashtest6  = testSet.map (lambda(f,x):(f,hashVector(x,hashtable_size,use_hash_signing)))


        if use_lexicon:
            logTimeIntervalWithMsg(s_time,'##### CREATE A DOC VECTOR AGAINST THE LEXICON   #####')
            train6=vectorise(train5,lexicon)
            #print ("traint6 sample:", train6.takeSample(True,4,0))
            test_6=vectorise(test_5,lexicon)

        # 3 Test whether the file is spam (i.e. the path contains spmsg) and replace the filename
        # by a 1 (spam) or 0 (ham) accordingly. Use map() to create an RDD of LabeledPoint objects.
        # See here http://spark.apache.org/docs/latest/mllib-naive-bayes.html for an example,
        # and here http://spark.apache.org/docs/latest/api/python/pyspark.mllib.regression.LabeledPoint-class.html
        # for the LabelledPoint documentation.

        logTimeIntervalWithMsg(s_time,'#####      TEST WHETHER FILE IS SPAM       #####')
        ##### REPLACE FILENAME BY 1 (spam) 0 (ham) #####

        if use_lexicon:
            train7 = train6.map (lambda(f,x):(1 if 'spmsg' in f else 0, x))
            #print ("train7 sample",train7.take(2))
        if use_hash:
            hashtrain7 = hashtrain6.map (lambda(f,x):(1 if 'spmsg' in f else 0, x))
            #print ("hashtrain7 sample",hashtrain7.take(2))



        logTimeIntervalWithMsg(s_time,'#####      MAP TO LABELLED POINTS      #####')
        if use_lexicon:
            train8 = train7.map (lambda (f,x):LabeledPoint(f,x))
        if use_hash:
            hashtrain8 = hashtrain7.map (lambda (f,x):LabeledPoint(f,x))


        #4 Use the created RDD of LabelledPoint objects to train the NaiveBayes and save
        # the model as a variable nbModel (again, use this example
        # http://spark.apache.org/ docs/latest/mllib-naive-bayes.html and here is the documentation
        # http://spark. apache.org/docs/latest/api/python/pyspark.mllib.regression.LabeledPoint-class. html).

        logTimeIntervalWithMsg(s_time,'#####      TRAIN THE NAIVE BAYES      #####')
        if use_lexicon:
            nbModel = NaiveBayes.train(train8, 1.0)
        if use_hash:
            hashnbModel =  NaiveBayes.train(hashtrain8, 1.0)


        # 5 Use the files from /data/extra/spam/bare/part2 and prepare them like in task 3).
        # Then use nbModel to predict the label for each vector you have and compare it to the original,
        # to test the performance of your classifier.

        #          """
        logTimeIntervalWithMsg(s_time,'#####      RUN THE PREDICTION      #####')
        if use_lexicon:
            test_7 = test_6.map(lambda (f,x):(1 if 'spmsg' in f else 0,int(nbModel.predict(x).item())))
            if use_log: print ("prediction sample: ",test_7.takeSample(False,20,0))

        if use_hash:
            hashtest7 = hashtest6.map(lambda (f,x):(1 if 'spmsg' in f else 0,int(hashnbModel.predict(x).item())))
            if use_log: print ("prediction sample: ",hashtest7.takeSample(False,20,0))


        logTimeIntervalWithMsg(s_time,'#####      EVALUATE THE RESULTS      #####')

        if 0:  #set to 1 for verbose reporting
            if use_lexicon:
                print('____________________________________')
                print('#####      EVALUATION      #####')
                print "\n"
                printConfusionDict(confusionDict(test_7.collect()))

            if use_hash:
                print('____________________________________')
                print('#####    HASH  EVALUATION      #####')
                print("#####    size %i" % (hashtable_size))
                print "\n"
                printConfusionDict(confusionDict(hashtest7.collect()))

        else: #1-line reporting (for spreadsheets)

            if use_lexicon:
                cd = confusionDict(test_7.collect())
                print("L\t\t%i\t%i\t%i\t%i\t%.3f\t%.3f\t%.3f\t%.3f" \
                      %(\
                        cd['TP'],cd['FP'],cd['FN'],cd['TN'],\
                        cd['Recall'],cd['Precision'],cd['Fmeasure'],cd['Accuracy']))
            if use_hash:
                cd = confusionDict(hashtest7.collect())
                print("%i\t%i\t%i\t%i\t%i\t%i\t%.3f\t%.3f\t%.3f\t%.3f" \
                      %(hashtable_size,use_hash_signing,\
                        cd['TP'],cd['FP'],cd['FN'],cd['TN'],\
                        cd['Recall'],cd['Precision'],cd['Fmeasure'],cd['Accuracy']))






        logTimeIntervalWithMsg(s_time,'#####      FINISHED      #####')