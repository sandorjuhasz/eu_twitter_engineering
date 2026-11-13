#!/usr/bin/env python3
"""Full-corpus c-TF-IDF representation and random examples for the selected final K."""
import json
import numpy as np, pandas as pd
from scipy import sparse
from sklearn.feature_extraction.text import CountVectorizer
from bertopic.vectorizers import ClassTfidfTransformer
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from pipeline_config import *
FINAL=KMEANS_DIR/"final_model"

def db_engine():
    with open(CONNECTION_PATH,encoding="utf-8") as f: c=json.load(f)
    return create_engine(URL.create("postgresql+psycopg2",username=c["user"],password=c["password"],host=c["host"],port=c["port"],database=c["database"]),pool_pre_ping=True)

def main():
    k=int(FINAL_K); labels_path=FINAL/f"topics_k{k}.npy"
    if not labels_path.exists(): raise FileNotFoundError("Run 05_finalize_selected_model.py first.")
    labels=np.load(labels_path,mmap_mode="r"); n=len(labels)
    rng=np.random.default_rng(12345); pieces=[]
    for t in range(k):
        idx=np.flatnonzero(labels==t); pieces.append(rng.choice(idx,size=min(VOCAB_SAMPLE_PER_TOPIC,len(idx)),replace=False))
    target=np.sort(np.concatenate(pieces)); eng=db_engine(); q=text(f"SELECT {TEXT_COLUMN} FROM {SOURCE_TABLE} WHERE {TEXT_COLUMN} IS NOT NULL AND n_cleaned_words >= {MIN_CLEANED_WORDS} ORDER BY {', '.join(ORDER_COLS)}")
    sample=[]; ptr=0; row=0
    with eng.connect().execution_options(stream_results=True) as conn:
        res=conn.execute(q)
        while True:
            rr=res.fetchmany(REPRESENTATION_FETCH_SIZE)
            if not rr: break
            end=row+len(rr)
            while ptr<len(target) and target[ptr]<end:
                sample.append(str(rr[int(target[ptr]-row)][0])); ptr+=1
            row=end
    if row!=n or ptr!=len(target): raise RuntimeError("DB/label alignment failure during vocabulary pass")
    v=CountVectorizer(lowercase=True,stop_words=None,ngram_range=NGRAM_RANGE,max_features=MAX_FEATURES); v.fit(sample); terms=np.asarray(v.get_feature_names_out())
    fixed=CountVectorizer(lowercase=True,stop_words=None,ngram_range=NGRAM_RANGE,vocabulary=v.vocabulary_)
    (FINAL/f"vocabulary_k{k}.txt").write_text("\n".join(terms.tolist())+"\n",encoding="utf-8")
    counts=sparse.csr_matrix((k,len(terms)),dtype=np.int64); reservoirs=[[] for _ in range(k)]; seen=np.zeros(k,dtype=np.int64); rrng=np.random.default_rng(12346); row=0
    with eng.connect().execution_options(stream_results=True) as conn:
        res=conn.execute(q)
        while True:
            rec=res.fetchmany(REPRESENTATION_FETCH_SIZE)
            if not rec: break
            end=row+len(rec); txt=[str(r[0]) for r in rec]; lab=np.asarray(labels[row:end],dtype=np.int16); x=fixed.transform(txt); ids=np.arange(len(rec),dtype=np.int32)
            ind=sparse.csr_matrix((np.ones(len(rec),dtype=np.int8),(ids,lab.astype(np.int32))),shape=(len(rec),k)); counts=counts+ind.T@x
            for t,s in zip(lab,txt):
                t=int(t); seen[t]+=1
                if len(reservoirs[t])<N_RANDOM_EXAMPLES: reservoirs[t].append(s)
                else:
                    j=int(rrng.integers(0,seen[t]));
                    if j<N_RANDOM_EXAMPLES: reservoirs[t][j]=s
            row=end
    eng.dispose()
    if row!=n or not np.array_equal(seen,np.bincount(labels,minlength=k)): raise RuntimeError("DB/label alignment failure during full pass")
    sparse.save_npz(FINAL/f"topic_term_counts_k{k}.npz",counts.tocsr(),compressed=True); ctf=ClassTfidfTransformer(reduce_frequent_words=True).fit_transform(counts).tocsr(); sparse.save_npz(FINAL/f"topic_ctfidf_k{k}.npz",ctf,compressed=True)
    top=[]
    for t in range(k):
        r=ctf.getrow(t); n_top=min(TOP_N_TERMS,r.nnz); loc=np.argpartition(r.data,-n_top)[-n_top:] if n_top else []
        if n_top: loc=loc[np.argsort(r.data[loc])[::-1]]
        for rank,j in enumerate(loc,1): top.append({"topic":t,"rank":rank,"term":str(terms[r.indices[j]]),"ctfidf":float(r.data[j])})
    pd.DataFrame(top).to_csv(FINAL/f"topic_top_terms_k{k}.csv",index=False)
    ex=[]
    for t,vals in enumerate(reservoirs):
        for rank,val in enumerate(vals,1): ex.append({"topic":t,"example_rank":rank,"text":val})
    pd.DataFrame(ex).to_csv(FINAL/f"topic_random_examples_k{k}.csv",index=False); print("DONE")
if __name__=="__main__": main()
