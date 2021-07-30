#!/usr/bin/env python3

"""
    biff a text and image extractor from pdf highlighted with reMarkable
    Copyright (C) 2020  Louis Delmas

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""

from fitz import open as fitzopen
from fitz import Rect , Matrix
from cv2 import dilate , erode,  subtract, findContours,  imdecode,  boundingRect, rectangle, RETR_CCOMP,  CHAIN_APPROX_SIMPLE
from numpy import ones,  empty,  zeros_like, lexsort,  frombuffer, uint8
from operator import itemgetter
from itertools import groupby
from re import sub
from odf.opendocument import OpenDocumentText
from odf.style import Style, TextProperties, ParagraphProperties, GraphicProperties
from odf.text import P
from odf.draw import Frame, Image
import argparse
from sys import argv
import os

def Page_Get_Highlights(doc,doc_text):
    
    for xref in range(1,doc.xrefLength()):
        cont=b""
        #try:
        #    cont=doc.xrefStream(xref)
        #except:
        #    continue
        if doc.isStream(xref):
            cont=doc.xrefStream(xref)
        else:
            continue       
        
        # different shades of yellow
        # yellows[0] is pre Remarkable 2.7 and yellows[1] is for highlights from Remarkable ver 2.7 and later
        yellows=[b"1 0.952941 0.658824 RG", b"0.992157 1 0.196078 rg",b"1 1 0 RG"]
        is_yellow=[True if y in cont else False for y in yellows]
        ind_yellow=[i for i in range(3) if is_yellow[i]==True]
        
        if len(ind_yellow)>0:
            cont=cont.replace(yellows[ind_yellow[0]],b"0 0 0 RG")
            cont=cont.replace(b"gs",b" ")
            #cont=re.sub(b"1 0 0 1 (.*) (.*) cm",b"1 0 0 1 0 0 cm",cont)
            cont=sub(b"q\n(.*) 0 0 (.*) (.*) (.*) cm",b"1 0 0 1 0 0 cm",cont)
            doc.updateStream(xref,cont)
            doc_text._deleteObject(xref)
        else:
            doc._deleteObject(xref)
    return doc,doc_text

def Page_Get_Rects(page,col):
    if col==1:
        x1,y1,x2,y2=page.CropBox
        x2/=2
        crop_rect=Rect(x1,y1,x2,y2)
        pix=page.getPixmap(clip=crop_rect)
        
    elif col==2:
        x1,y1,x2,y2=page.CropBox
        x1=x2/2
        crop_rect=Rect(x1,y1,x2,y2)
        pix=page.getPixmap(clip=crop_rect)
          
    else:
        pix=page.getPixmap(clip=page.CropBox)
        
    pix=pix.getPNGData()
    nparr = frombuffer(pix, uint8)
    img = 255-imdecode(nparr,0)
    
    #strategy is now to not print images too small
    #kernel = ones((3,3), uint8)
    #img=dilate(img,kernel,iterations = 2)
    #img=erode(img,kernel,iterations = 2)
    contour,hierarchy = findContours(img,RETR_CCOMP,CHAIN_APPROX_SIMPLE)
    
    nb_contour=len(contour)
    rects=empty((nb_contour,4))
    rects_sorted=empty((nb_contour,4))
    hierarchy_sorted=empty((nb_contour,4))
    
    #image with filled bounding rects
    img_rects=zeros_like(img)
        
    for i in range(nb_contour):
        rects[i] = boundingRect(contour[i])
        x,y,w,h=rects[i].astype(int)
        img_rects = rectangle(img_rects,(x,y),(x+w,y+h),255,-1)
        
    #some dilations of initial images to isolate part of the bounding rects that were not highlighted
    kernelh = ones((1,3), uint8)
    img=dilate(img,kernelh,iterations = 10)
    kernelv = ones((3,1), uint8)
    img=dilate(img,kernelv,iterations = 10)

    img3=subtract(img_rects,img)
    #dilate the rectangles to exclude
    img3=dilate(img3,kernelv,iterations = 10)   
    #contours to exclude
    Xcontour,Xhierarchy = findContours(img3,RETR_CCOMP,CHAIN_APPROX_SIMPLE)
    
    nb_Xcontour=len(Xcontour)
    Xrects=empty((nb_Xcontour,4))
    #bounding box of contours to exclude  
    for i in range(nb_Xcontour):
        Xrects[i] = boundingRect(Xcontour[i])      
        
        
        
    rects[:,2]=rects[:,0]+rects[:,2]
    rects[:,3]=rects[:,1]+rects[:,3]
    ind_sorted=lexsort((rects[:,0],rects[:,1]))
    
    Xrects[:,2]=Xrects[:,0]+Xrects[:,2]
    Xrects[:,3]=Xrects[:,1]+Xrects[:,3]
    #no need to sort excluded contours we'll just iterate over all

    for i in range(nb_contour):
        rects_sorted[i]=rects[ind_sorted[i]]
        hierarchy_sorted[i]=hierarchy[0,ind_sorted[i],:]
    
    if col==2:
        rects_sorted[:,0]+=x1
        rects_sorted[:,2]+=x1
        Xrects[:,0]+=x1
        Xrects[:,2]+=x1
        
    return rects_sorted,hierarchy_sorted,Xrects

def Page_Rect_get_Text(doc,page_num,rects,output):
    page=doc[page_num]
    words = page.getText("words")
    output.write("_"*30+"\n")
    output.write(f"page {page_num+1}\n")
    for i in range(rects.shape[0]):
        output.write("\n")
        rect=Rect(rects[i,0],rects[i,1],rects[i,2],rects[i,3])
        mywords = [w for w in words if Rect(w[:4]) in rect]
        mywords.sort(key=itemgetter(3, 0))  # sort by y1, x0 of the word rect
        group = groupby(mywords, key=itemgetter(3))
        for y1, gwords in group:
            output.write(" ".join(w[4] for w in gwords).replace("\n",""))
            output.write("\n")


def Page_Rect_get_Text_odf(doc,page_num,rects,hierarchy,Xrects,output,style_p,style_i,img_quality,col):
    page=doc[page_num]
    words = page.getText("words")
    output.text.addElement(P(stylename=style_p,text="_"*60))
    if col==1 or col==2:
        output.text.addElement(P(stylename=style_p,text=f"page {page_num+1} - column {col}"))
    else:
        output.text.addElement(P(stylename=style_p,text=f"page {page_num+1}"))
    for i in range(rects.shape[0]):
        if hierarchy[i,3]==-1:
        	#modify bounds of rectangle to work with highlights from Remarkable ver 2.7 and later
            rect=Rect(rects[i,0]-10.,rects[i,1]-5.,rects[i,2]+25.,rects[i,3]+5.)
            allwords = [w for w in words if Rect(w[:4]) in rect]
            # iterate over all rects to exclude
            mywords=[]
            for w in allwords:
                exclude=0
                for Xrect in Xrects:
                    xg=(w[0]+w[2])/2
                    yg=(w[1]+w[3])/2
                    if Rect(Xrect).contains((xg,yg)):
                        exclude=1
                if exclude==0:
                    mywords.append(w)

            mywords.sort(key=itemgetter(3, 0))  # sort by y1, x0 of the word rect
            group = groupby(mywords, key=itemgetter(3))
            
            output.text.addElement(P(stylename=style_p,text=""))
            out_text=P(stylename=style_p,text="")
            for y1, gwords in group:
                out_text.addText(" ".join(w[4] for w in gwords).replace("\n"," "))
                out_text.addText(" ")
            output.text.addElement(out_text)
        if hierarchy[i,3]!=-1:

            clip = Rect(rects[i,0],rects[i,1],rects[i,2],rects[i,3])
            #taking into account quality
            img_qual=img_quality/50.
            
            pix = page.getPixmap(matrix=Matrix(img_qual,img_qual),clip=clip)
            
            name_image=f"Pictures/image-{page.number}-{col}{i}.png"
            pix_png=pix.getPNGData()
            h=pix.height/pix.xres
            w=pix.width/pix.yres
            #if quality is larger than 2 keep the frame the same as if it was 2
            h*=2/img_qual
            w*=2/img_qual
            #if image is too small (h<20px) it is probably an artifact
            #so do not print it
            if pix.height*2/img_qual>20:
                output.text.addElement(P(stylename=style_p,text=""))
                out_img=P()
                frame=Frame(stylename=style_i, width=f"{w}in",height=f"{h}in",anchortype="paragraph")
                href=output.addPicture(name_image,mediatype="png",content=pix_png)#
                frame.addElement(Image(href=f"./{href}"))
                out_img.addElement(frame)
                output.text.addElement(out_img)
    return output
            
"""
OLD
def extract_highlight(name):
    open(f"{name}.txt", 'w').close()
    output=open(f"{name}.txt","a")
    doc_mask=fitzopen(name)
    doc_text=fitzopen(name)
    nb_pages=doc_text.pageCount
    for i in range(nb_pages):
        rect,hierarchy=Page_Get_Rects(doc_mask,name,i)
        if rect.shape[0]>0:
            Page_Rect_get_Text(doc_text,name,i,rect,output)
    output.close()
"""

def extract_highlight_odf(name,img_quality,two_col,output_folder=None):
    textdoc = OpenDocumentText()
    doc_mask=fitzopen(name)
    doc_text=fitzopen(name)
    nb_pages=doc_text.pageCount
    #create style for paragraph
    style_p=Style(name="P1",family="paragraph",parentstylename="Standard")
    p_prop = ParagraphProperties(textalign="justify",justifysingleword="false")
    style_p.addElement(p_prop)
    textdoc.automaticstyles.addElement(style_p)
    
    #create style for images
    style_i=Style(name="fr1", family="graphic", parentstylename="Graphics")
    i_prop=GraphicProperties(wrap="none",runthrough="foreground", horizontalpos="center",horizontalrel="paragraph")
    style_i.addElement(i_prop)
    textdoc.automaticstyles.addElement(style_i)
    
    #insert pdf file name
    textdoc.text.addElement(P(stylename=style_p,text=f"{name}\n\n"))
    
    #isolate highlights in _mask and text in _text
    doc_mask,doc_text=Page_Get_Highlights(doc_mask,doc_text)
    
    #iterate over pages to create rectangles to extract
    for i in range(nb_pages):
        
        if two_col==True:
            #colonnes
            for col in [1,2]:
                rect,hierarchy,Xrects=Page_Get_Rects(doc_mask[i],col)

                if rect.shape[0]>0:
                    textdoc=Page_Rect_get_Text_odf(doc_text,i,rect,hierarchy,Xrects,textdoc,style_p,style_i,img_quality,col)
        else:
            col=0
            rect,hierarchy,Xrects=Page_Get_Rects(doc_mask[i],col)
            if rect.shape[0]>0:
                textdoc=Page_Rect_get_Text_odf(doc_text,i,rect,hierarchy,Xrects,textdoc,style_p,style_i,img_quality,col)
    if output_folder is not None:
        basename=os.path.basename(name)
        outname=basename.replace(".pdf",".odt")
        outname=os.path.join(output_folder,outname)
        textdoc.save(outname)
    else:
        textdoc.save(name.replace(".pdf",".odt"))
    doc_mask.close()
    doc_text.close()

def run():
    parser=argparse.ArgumentParser(description='''Extract highlighted text and framed images from PDF(s) generated with reMarkable tablet to Openoffice text document. Highlighted text will be exported as text. Framed areas will be cropped as images.''',
                                   epilog="""  biff  Copyright (C) 2020  Louis DELMAS
                                   This program comes with ABSOLUTELY NO WARRANTY.
                                   This is free software, and you are welcome to redistribute it
                                   under certain conditions; see COPYING for details.""",)
    parser.add_argument('pdf', nargs='*', help='PDF files',)
    parser.add_argument('-c', '--two-columns', help='For two-columns pdf, parse columns from left to right',action='store_true',)
    parser.add_argument('-q','--quality',help='Extract resolution extracted images in PPI, default=150 PPI', type=int, default=100,)
    parser.add_argument('-o','--output-folder',help='Output folder for ODT files', type=str,default=None)

    args=parser.parse_args()
    #print(args)
    
    for i in range(len(args.pdf)):
        if not os.path.exists(args.pdf[i]):
            parser.error(f'The file "{args.pdf[i]}" does not exist.')
        if args.pdf[i].endswith(".pdf"):
            if args.output_folder is None:
                output_folder=None #args.pdf[i].replace(os.path.basename(args.pdf[i]),'')
            elif os.path.exists(args.output_folder):
                output_folder=args.output_folder
                
            print(f"Converting {args.pdf[i]} ...")
            extract_highlight_odf(args.pdf[i],args.quality,args.two_columns,output_folder=output_folder)
        else:
            print(f"{args.pdf[i]} is not a pdf")
            
def gui(filename,input_folder,output_folder,img_quality,two_col):
    if not os.path.exists(input_folder) or not os.path.exists(output_folder):
        return f'The folder "{args.pdf[i]}" does not exist.'
    
    elif not os.path.exists(os.path.join(input_folder,filename)):
        return f'The folder "{args.pdf[i]}" does not exist.'
        
    elif filename.endswith(".pdf"):
        name=os.path.join(input_folder,filename)
        extract_highlight_odf(name,img_quality,two_col,output_folder=output_folder)
        return f"Converting {filename}...."
    
    else:
        return f"{args.pdf[i]} is not a pdf"
