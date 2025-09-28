from sacrebleu import corpus_bleu
from bert_score import score
import torch
from sacrebleu import corpus_bleu, sentence_bleu
import numpy as np
import torch.nn.functional as F
from nltk.translate.bleu_score import sentence_bleu, corpus_bleu, SmoothingFunction
import matplotlib.pyplot as plt

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
    
    smooth_fn = SmoothingFunction().method1  # only used for sentence BLEU
    
    with torch.no_grad():
        for i, (ja_text, en_ref) in enumerate(zip(test_ja[:max_samples], test_en[:max_samples])):
            # Tokenize input
            inputs = tokenizer(
                ja_text, return_tensors="pt",
                max_length=128, truncation=True
            ).to("cuda")
            
            # Generate translation
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
            
            # Sentence-level BLEU (tokenized)
            try:
                gen_tokens = generated.split()
                ref_tokens = en_ref.split()
                sent_bleu = sentence_bleu(
                    [ref_tokens], gen_tokens,
                    smoothing_function=smooth_fn
                ) * 100
            except:
                sent_bleu = 0.0
            sentence_bleus.append(sent_bleu)
            
            # Sentence-level BERTScore
            try:
                _, _, F1 = score([generated], [en_ref], lang="en", verbose=False)
                sent_bert = F1.item()
            except:
                sent_bert = 0.0
            sentence_berts.append(sent_bert)
            
            # Print examples
            if i < 5:
                print(f"\nExample {i+1}:")
                print(f"JA:  {ja_text}")
                print(f"REF: {en_ref}")
                print(f"GEN: {generated}")
                print(f"BLEU: {sent_bleu:.2f}, BERTScore F1: {sent_bert:.3f}")
    
    # Corpus-level BLEU (SacreBLEU, raw text)
    try:
        corpus_bleu_score = corpus_bleu(
            generated_translations,
            [reference_translations],   # references must be a list of lists
            smooth_method="exp"
        ).score
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


def tolkienize_plot():
    """Apply Middle-earth styling to the current matplotlib plot"""
    import matplotlib.pyplot as plt
    
    colors = {
        'gold': '#d4af37',
        'light_gold': '#f4e968', 
        'text': '#e8d5a0',
        'bg_dark': '#1a1a2e',
        'bg_mid': '#16213e',
        'ring_fire': '#ff6b35',  # For negative sentiment
        'shire_green': '#7fb069'  # For positive sentiment
    }
    
    ax = plt.gca()
    fig = plt.gcf()
    
    # Background - dark like the depths of Moria
    ax.set_facecolor(colors['bg_dark'])
    fig.patch.set_facecolor(colors['bg_mid'])
    
    # Grid - subtle golden lines like elvish script
    ax.grid(True, color=colors['gold'], alpha=0.3, linestyle='--', linewidth=0.8)
    
    # Spines - golden borders worthy of the One Ring
    for spine in ax.spines.values():
        spine.set_color(colors['gold'])
        spine.set_linewidth(2)
    
    # Text colors - parchment gold
    ax.tick_params(colors=colors['text'], which='both')
    ax.xaxis.label.set_color(colors['text'])
    ax.yaxis.label.set_color(colors['text'])
    ax.title.set_color(colors['gold'])
    
    # Legend styling
    legend = ax.get_legend()
    if legend:
        legend.get_frame().set_facecolor(colors['bg_dark'])
        legend.get_frame().set_edgecolor(colors['gold'])
        legend.get_frame().set_linewidth(1.5)
        legend.get_frame().set_alpha(0.9)
        for text in legend.get_texts():
            text.set_color(colors['text'])