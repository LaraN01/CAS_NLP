from sacrebleu import corpus_bleu
from bert_score import score
from transformers import MBartForConditionalGeneration, MBart50TokenizerFast
import torch
from transformers import Trainer, TrainingArguments
from datasets import Dataset
from transformers import DataCollatorForSeq2Seq
from sacrebleu import corpus_bleu, sentence_bleu
import numpy as np
import torch.nn.functional as F
import random
import copy
from bert_score import score
from nltk.translate.bleu_score import sentence_bleu, corpus_bleu, SmoothingFunction

from sacrebleu import corpus_bleu

def evaluate_mt(ebmt_outputs, y_test):
    candidates = list(ebmt_outputs)
    references = [list(y_test)]  # sacrebleu wants list of reference lists

    # Corpus BLEU
    bleu_score = corpus_bleu(candidates, references).score

    # BERTScore
    P, R, F1 = score(candidates, list(y_test), lang="en", verbose=False)
    bert_f1 = F1.mean().item()

    print("MT evaluation")
    print("-----------------")
    print(f"Corpus BLEU: {bleu_score:.2f}")
    print(f"Corpus BERTScore F1: {bert_f1:.3f}")
    return bleu_score, bert_f1



def evaluate_model(model, tokenizer, test_ja, test_en, max_samples=100):
    """Evaluate model on test set with BLEU and BERTScore"""
    model.eval()
    
    generated_translations = []
    reference_translations = []
    sentence_bleus = []
    sentence_berts = []
    
    print(f"Evaluating on {min(len(test_ja), max_samples)} samples...")
    
    smooth_fn = SmoothingFunction().method1  # prevents zero BLEU for short sentences
    
    with torch.no_grad():
        for i, (ja_text, en_ref) in enumerate(zip(test_ja[:max_samples], test_en[:max_samples])):
            # Tokenize input
            inputs = tokenizer(ja_text, return_tensors="pt", max_length=128, truncation=True).to("cuda")
            
            # Generate translation (beam search for quality)
            outputs = model.generate(
                **inputs,
                forced_bos_token_id=tokenizer.lang_code_to_id["en_XX"],
                max_length=128,
                num_beams=4,
                early_stopping=True,
                pad_token_id=tokenizer.pad_token_id
            )
            
            generated = tokenizer.decode(outputs[0], skip_special_tokens=True)
            
            # Store results
            generated_translations.append(generated)
            reference_translations.append(en_ref)
            
            # Compute sentence-level BLEU (tokenized)
            try:
                gen_tokens = generated.split()
                ref_tokens = en_ref.split()
                sent_bleu = sentence_bleu([ref_tokens], gen_tokens, smoothing_function=smooth_fn) * 100
            except:
                sent_bleu = 0.0
            sentence_bleus.append(sent_bleu)
            
            # Compute sentence-level BERTScore (F1)
            try:
                _, _, F1 = score([generated], [en_ref], lang="en", verbose=False)
                sent_bert = F1.item()
            except:
                sent_bert = 0.0
            sentence_berts.append(sent_bert)
            
            # Print a few examples
            if i < 5:
                print(f"\nExample {i+1}:")
                print(f"JA:  {ja_text}")
                print(f"REF: {en_ref}")
                print(f"GEN: {generated}")
                print(f"BLEU: {sent_bleu:.2f}, BERTScore F1: {sent_bert:.3f}")
    
    # Corpus-level BLEU (tokenized)
    try:
        corpus_bleu_score = corpus_bleu(
            [[ref.split()] for ref in reference_translations],
            [gen.split() for gen in generated_translations]
        ) * 100
    except:
        corpus_bleu_score = 0.0
    
    # Corpus-level BERTScore
    try:
        _, _, F1 = score(generated_translations, reference_translations, lang="en", verbose=False)
        corpus_bert_score = F1.mean().item()
    except:
        corpus_bert_score = 0.0
    
    return {
        'corpus_bleu': corpus_bleu_score,
        'avg_sentence_bleu': np.mean(sentence_bleus),
        'std_sentence_bleu': np.std(sentence_bleus),
        'corpus_bert': corpus_bert_score,
        'avg_sentence_bert': np.mean(sentence_berts),
        'std_sentence_bert': np.std(sentence_berts),
        'generated_translations': generated_translations,
        'reference_translations': reference_translations,
        'sentence_bleus': sentence_bleus,
        'sentence_berts': sentence_berts
    }