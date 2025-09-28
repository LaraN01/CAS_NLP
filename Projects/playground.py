import os
from moviepy.editor import *
from gtts import gTTS
import requests
from PIL import Image
import tempfile
import urllib.parse

class MedievalDocumentaryCreator:
    def __init__(self, output_dir="output"):
        self.output_dir = output_dir
        self.images_dir = os.path.join(output_dir, "images")
        os.makedirs(output_dir, exist_ok=True)
        os.makedirs(self.images_dir, exist_ok=True)
    
    def download_medieval_images(self):
        """Download medieval images for the documentary"""
        # Some good medieval images from Wikimedia Commons and other sources
        image_urls = [
            # Medieval castle
            "https://upload.wikimedia.org/wikipedia/commons/thumb/8/82/Neuschwanstein_Castle_LOC_print.jpg/1200px-Neuschwanstein_Castle_LOC_print.jpg",
            # Medieval feast
            "https://upload.wikimedia.org/wikipedia/commons/thumb/4/4b/Wedding_Feast_at_Bermondsey_Priory.jpg/1200px-Wedding_Feast_at_Bermondsey_Priory.jpg",
            # Medieval manuscript
            "https://upload.wikimedia.org/wikipedia/commons/thumb/f/f0/Book_of_Kells_folio_34r_detail.jpg/800px-Book_of_Kells_folio_34r_detail.jpg",
            # Medieval nobles
            "https://upload.wikimedia.org/wikipedia/commons/thumb/0/07/Giovanni_Boccaccio_Illustration.jpg/800px-Giovanni_Boccaccio_Illustration.jpg",
            # Medieval cats (for Merlin and Casper!)
            "https://upload.wikimedia.org/wikipedia/commons/thumb/c/c4/Medieval_cats_-_British_Library_Royal_MS_12_F_xiii_f._45v_%28detail%29.jpg/800px-Medieval_cats_-_British_Library_Royal_MS_12_F_xiii_f._45v_%28detail%29.jpg",
            # Medieval daily life
            "https://upload.wikimedia.org/wikipedia/commons/thumb/1/1c/Medieval_writing_desk.jpg/800px-Medieval_writing_desk.jpg"
        ]
        
        downloaded_paths = []
        for i, url in enumerate(image_urls):
            try:
                response = requests.get(url, timeout=10)
                if response.status_code == 200:
                    filename = f"medieval_image_{i+1}.jpg"
                    filepath = os.path.join(self.images_dir, filename)
                    
                    with open(filepath, 'wb') as f:
                        f.write(response.content)
                    
                    downloaded_paths.append(filepath)
                    print(f"Downloaded: {filename}")
                else:
                    print(f"Failed to download image {i+1}")
            except Exception as e:
                print(f"Error downloading image {i+1}: {e}")
        
        return downloaded_paths
    def text_to_speech(self, text, output_file="narration.mp3", lang='it'):
        """Convert Italian text to speech with slower, more dramatic pace"""
        # Split text into smaller chunks for better pronunciation
        tts = gTTS(text=text, lang=lang, slow=True)  # slow=True for more dramatic effect
        filepath = os.path.join(self.output_dir, output_file)
        tts.save(filepath)
        return filepath
    
    def create_image_clip(self, image_path, duration, size=(1920, 1080)):
        """Create a video clip from a single image with ken burns effect"""
        clip = (ImageClip(image_path)
                .set_duration(duration)
                .resize(size)
                .set_position('center'))
        
        # Add subtle zoom effect (Ken Burns)
        clip = clip.resize(lambda t: 1 + 0.02*t)
        
        return clip
    
    def add_medieval_transition(self, clip):
        """Add a fade transition that feels medieval"""
        return clip.fadein(0.5).fadeout(0.5)
    
    def create_documentary(self, text, image_paths, background_music_path=None):
        """Create the complete documentary video"""
        
        # Step 1: Create narration
        print("Creating narration...")
        narration_path = self.text_to_speech(text)
        audio = AudioFileClip(narration_path)
        total_duration = audio.duration
        
        # Step 2: Create video clips from images
        print("Processing images...")
        image_duration = total_duration / len(image_paths)
        video_clips = []
        
        for img_path in image_paths:
            clip = self.create_image_clip(img_path, image_duration)
            clip = self.add_medieval_transition(clip)
            video_clips.append(clip)
        
        # Step 3: Concatenate all image clips
        video = concatenate_videoclips(video_clips)
        
        # Step 4: Add narration
        final_video = video.set_audio(audio)
        
        # Step 5: Add background music if provided
        if background_music_path:
            background_music = (AudioFileClip(background_music_path)
                              .subclip(0, total_duration)
                              .volumex(0.3))  # Lower volume for background
            
            # Mix narration with background music
            mixed_audio = CompositeAudioClip([audio, background_music])
            final_video = final_video.set_audio(mixed_audio)
        
        # Step 6: Add title and credits
        final_video = self.add_title_and_credits(final_video, 
                                               "Cronache Medievali", 
                                               "Una Storia del Nostro Tempo")
        
        return final_video
    
    def add_title_and_credits(self, video, title, subtitle):
        """Add medieval-style title and credits"""
        # Title clip
        title_clip = (TextClip(title, 
                              fontsize=70, 
                              font='Arial-Bold',
                              color='gold',
                              stroke_color='black',
                              stroke_width=2)
                     .set_duration(3)
                     .set_position('center')
                     .set_start(0))
        
        subtitle_clip = (TextClip(subtitle,
                                 fontsize=40,
                                 font='Arial',
                                 color='white',
                                 stroke_color='black',
                                 stroke_width=1)
                        .set_duration(3)
                        .set_position(('center', 'bottom'))
                        .set_start(0.5))
        
        # Create a black background for title
        title_bg = ColorClip(size=video.size, color=(0,0,0)).set_duration(3)
        
        # Composite title sequence
        title_sequence = CompositeVideoClip([title_bg, title_clip, subtitle_clip])
        
        # Add title to beginning of video
        final_video = concatenate_videoclips([title_sequence, video])
        
        return final_video
    
    def render_video(self, video, output_filename="medieval_documentary.mp4"):
        """Render the final video"""
        output_path = os.path.join(self.output_dir, output_filename)
        print(f"Rendering video to {output_path}...")
        
        video.write_videofile(output_path, 
                             fps=24, 
                             codec='libx264',
                             audio_codec='aac',
                             temp_audiofile='temp-audio.m4a',
                             remove_temp=True)
        
        return output_path

# Example usage for your sister's birthday video!
def create_birthday_documentary():
    # Your beautiful medieval text
    medieval_text = """
        Correva l’anno 2023 di nostro Signore, allorché Sir Luca, cavalier del Barolo, ardito si fece ad approcciar la nobil Lady Daisy du Champagne con la lauda proposta del viver assieme. Ma correva pur il tempo nel qual Lady Daisy s’occupava del mal delle genti in quel di HR, sì che assai poco spazio le restava per le cortesie del gioviale gentiluomo, quand’anche egli si prodigasse.

        E nondimeno nello scenario dimoravan ancor gli altri rampolli della stirpe: l’irrequieto fratello, giovane signorino della casata, che con poca misura e assai baldoria turbava la quiete della dimora, in compagnia della sorella mezzana, la nobil Lady Lara del Bonarda, di vivace ardire non men che di gentile lignaggio.

        Il nobil signorino, Erik von Feldschlossen, era intanto tenuto a recarsi in quel di Brug-Land, a perseguir l’educazione presso la rinomata Accademia delle Scienze, loco in cui gl’ingegnosi s’illudon d’incatenar fulmini e di trarne elettricità. E fu per tal ragione che parve scelta illuminata ai tre nobilotti consumar ancor un tratto della lor verde etade nella lieta compagnia l’un dell’altro.

        Trovaron quindi consueto loco in quel di Magden, tranquillo villaggio dell’Elvezia, dove Lady Daisy si dedicò al sostegno de’ poretti di Franconia, con santa pazienza a tollerar lagnanze d’ogni sorta, mentre Lady Lara si dava non a sanar gli affanni della mente ma del corpo, con arti d’alchimia e creazione.

        Così i tre nobilotti cominciaron a trascorrer liete ore in Argaulandia, tra serate soavi e lauti conviti di pane e pomodoro (pietanza che oggidì rozzi chiaman Pizza), e non mancava talvolta qualche scaramuccia. Frequenti eran pure le gioviali adunanze con Sir Luca, sempre ospite gradito, insieme a Lady Silvia von Trondheim. Curioso avvenimento fu quand’essi, messisi in abiti civili per mescolarsi alla plebe, si recarono in quel loco ove i paesani van a saltare, detto “jump-hall”: ivi, dimentichi d’ogni nobiltà, anch’essi si dettero ai piaceri mondani del salto e del giuoco.

        Né mancavan poi i banchetti nella dimora che fu detta Magdeburg, ove pur, a dir vero, il maggior interesse degli ospiti non cadeva mai sui signori di casa, bensì sul lor animali di compagnia, messer Merlin Peloso, micio a pelo lungo, di stirpe borghese ma di portamento regale e lo nuovo arrivato messer Casper, di minor massa ma altrettanta pelosità. 

        Così scorser giorni e anni in allegrezza, mentre Sir Luca già si domandava se dovesse farsi più canuto e più vetusto del suo amato vino prima d’aver l’agognata dama al suo fianco.

        Sopraggiunse infine l’anno 2025 di nostro Signore, e Lady Daisy du Champagne benignamente acconsentì all’ideata proposta. Onde la giovane coppia si mise in cerca di degna dimora, secondo i lor nobili requisiti e domandazioni, e trovaron papabile candidato in quel di Maran Eparnier, loco che si gloria di lago e di buone vivande, quando pur non vi si faccia abuso di panna. Dopo lunghe esitazioni, la dama accettò lo nuovo loco, seppur con malinconia: ché lasciar dovea i lieti fratelli e compagni d’avventure.  Anche i fratelli, dal canto loro, doleron la novella, ma al contempo gioiron pel destino della giovanile coppia e per la vita lor ventura assieme. Ben sapevano che gli sarebber mancati li momenti gioiosi e li minuti dettagli; ché un’intera stanza parria d’improvviso vuota e malinconica. Pure la terra di Maran Eparnier non giaceva poi sì lontana, e con poche ore di viaggio sopra le carrozze dell’elvetica SBB agevolmente si sarebber potuti ricongiunger. Oltremodo, gli allemanofori medesimi spesso traevan conforto dal parlar con la gentil Lady di Champagne e dal ritrovar serenità in sua presenza. Onde i due fratellini la confortaron, assicurandole che lo scorrer del tempo non muterebbe l’affetto né la letizia, e che sempre avrebbero potuto gioire assieme nella Magdenica dimora, ove la dama sarebbe rimasta perpetuamente benvenuta. E così la cronaca si compie: ché se i luoghi mutano e le stanze paiono vuote, saldo pur resta il vincolo de sangue e d’amor fraterno, che niuna distanza potrà mai spezzare.

    """
    
    # Initialize creator
    creator = MedievalDocumentaryCreator()
    
    # Download images automatically
    print("Downloading medieval images...")
    image_paths = creator.download_medieval_images()
    
    if not image_paths:
        print("No images downloaded. Please check your internet connection.")
        return
    
    # Create the documentary
    print("Creating your sister's birthday documentary...")
    video = creator.create_documentary(
        text=medieval_text,
        image_paths=image_paths,
        background_music_path=None  # Add path if you have medieval music
    )
    
    # Render final video with a special birthday filename
    output_path = creator.render_video(video, "Happy_Birthday_Medieval_Chronicle.mp4")
    print(f"🎂 Birthday documentary created successfully: {output_path}")
    print("Your sister will love this medieval tale!")

if __name__ == "__main__":
    create_birthday_documentary()