#!/usr/bin/env python

# apologies and thanks to Jesper Skov <jskov@cygnus.co.uk> for theft
# of his gnome-canvas example for python

import GTK, GDK
from gtk import *
from gnome.ui import *
from whrandom import *
from twisted.reality import Reality, Thing
from twisted.geometry import layout, linepoints, waypoint
#from inherit import grounds2
#grounds=grounds2
#from twisted import reality
#grounds.damien=reality.default_reality['Damien']
#from inherit import grounds
from random import randint
import sys

import GdkImlib

names=['alpha',
	   'beta',
	   'test',
	   'north',
	   'south',
	   'east',
	   'circle room',
	   "Gruagah's Den",
	   'Troll Room',
	   'Palace Entranceway']



def roomname():
	return names[randint(0,len(names)-1)]


I=(0,1)
II=(1,0)
III=(0,-1)
IV=(-1,0)
	
class MapLine:
	def __init__(self,first,second,label):
		
		self.first=first
		self.second=second
		self.name=label
		
		self.widget=first.editor.canvas.root().add(
			'line',
			points=(100,100, 200,200),
			last_arrowhead=1, arrow_shape_a=10,
			arrow_shape_b=10, arrow_shape_c=5,
			fill_color='#777777')

		self.wtext=first.editor.canvas.root().add(
			'text',text=label,x=100,y=100,font='fixed',
			fill_color='black',
			anchor=GTK.ANCHOR_CENTER,
			justification=GTK.JUSTIFY_CENTER)

		self.widget.lower_to_bottom()
		
		second.to_exits.append(self)
		first.from_exits.append(self)

		self.locate()

	def locate(self):
		
		points=linepoints(self.first.bounds(),
						  self.second.bounds())
		
		self.widget.set(points=points)
		av = apply(waypoint,points)
		
		self.wtext.set(x=av[0],y=av[1])
		
x1=0
y1=0
x2=50
y2=50

class MapItem:
	mark=0
	def __init__(self,editor,name):
		global x1, x2, y1, y2
		x1=x1+1;x2=x2+1;y1=y1+1;y2=y2+1
		type = 'rect'
		textx=x1+25; texty = y1+25
		ttype = 'text'
		self.name=name

		self.widget=editor.canvas.root().add(
			type, x1=x1, y1=y1, x2=x2, y2=y2, 
			fill_color='white', outline_color='black',
			width_units=1.0)
		
		self.wtext=editor.canvas.root().add(
			ttype, text=name,
			x=textx, y=texty,
			anchor=GTK.ANCHOR_CENTER,
			justification=GTK.JUSTIFY_CENTER,
			font='fixed', # man, this SUCKED!
			fill_color='black')
		
		self.widget.connect('event',self.item_event)
		self.wtext.connect('event',self.item_event)
	
		self.editor=editor
		self.to_exits=[]
		self.from_exits=[]
		self._x=x1
		self._y=y1
		self.width=50
		self.height=50


	def bounds(self):
		return self.widget.get_bounds()
		
	def single_click(self):
		self.editor.select(self)
		
	def double_click(self):
		pass

	def exit_to(self,other):
		ml=MapLine(self,other,roomname())

	def drag_start(self,x,y):
		self.drag_continue(x,y)

	def drag_continue(self,x,y):
		self._x=x
		self._y=y

	def drag_stop(self,x,y):
		if not hasattr(self,'dragging'):
			self.single_click()
		else:
			self.editor.update_scroll()
			del self.dragging

	def drag(self,x,y):
		self.dragging=1
		mx,my= x-self._x, y-self._y
		self.widget.move(mx,my)
		self.wtext.move(mx,my)
		for i in self.from_exits:
			i.locate()
		for i in self.to_exits:
			i.locate()
		self.drag_continue(x,y)

	def enter(self):
		self.widget.set(width_units=3)

	def leave(self):
		self.widget.set(width_units=1)

	def select(self):
		self.widget.set(fill_color="grey")
		self.widget.raise_to_top()
		self.wtext.raise_to_top()

	def exit_select(self):
		self.widget.set(fill_color="blue")

	def deselect(self):
		self.widget.set(fill_color="white")
		
	def item_event(self, widget, event=None):
		if event.type == GDK.BUTTON_PRESS:
			if event.button == 1:
				self.drag_start(event.x,event.y)
				return TRUE
		if event.type == GDK.BUTTON_RELEASE:
			if event.button == 1:
				self.drag_stop(event.x, event.y)
				return TRUE
			
		elif event.type == GDK._2BUTTON_PRESS:
			self.double_click()
			return TRUE
		elif event.type == GDK.MOTION_NOTIFY:
			if event.state & GDK.BUTTON1_MASK:
				self.drag(event.x,event.y)
				return TRUE
		elif event.type == GDK.ENTER_NOTIFY:
			self.enter()
			return TRUE
		elif event.type == GDK.LEAVE_NOTIFY:
			self.leave()
			return TRUE
		return FALSE


class Tool:
	name="NO TOOL"
	def __init__(self, editor):
		self.editor=editor
		if not editor.default:
			editor.default=self

	def fin(self):
		self.editor.default_tool()
		
	def done(self):
		self.widget.set_active(0)
		self.finish()

	def choose(self,widget=None):
		if not widget or widget.active:
			if self.editor.tool != self:
				self.editor.detool()
				self.editor.tool=self
				self.widget.set_active(1)
				self.start()
		elif widget:
			if self.editor.tool == self:
				widget.set_active(1)
		
	def select(self, item): pass
	def start(self): pass
	def finish(self): pass

class SelectTool(Tool):
	name="Select"
	selected=None
	
	def select(self, item):
		if self.selected:
			self.selected.deselect()
		item.select()
		self.selected=item

	def finish(self):
		if self.selected:
			self.selected.deselect()

class PlaceTool(Tool):
	"""
	Place an item
	"""
	name="Place"

class SourceTool(Tool):
	"""
	open source
	"""
	name="Source"

class EnterTool(Tool):
	"""
	enter a room
	"""
	name="Enter ->"

class LeaveTool(Tool):
	"""
	exit a room
	"""
	name="Leave ../"
	
class ExitTool(Tool):
	name="Create Exit"
	first=None
	second=None
	
	def select(self, item):
		if self.first:
			self.first.exit_to(item)
			self.fin()
		else:
			self.first=item
			self.first.exit_select()

	def finish(self):
		if self.first:
			self.first.deselect()
			del self.first

class MapEditor:
	tool=None
	def __init__(self):
		self.width = 400
		self.height = 400

		self.default=None

	def select(self, item):
		if self.tool:
			self.tool.select(item)

	def detool(self):
		if self.tool:
			tool=self.tool
			del self.tool
			tool.done()

	def default_tool(self):
		self.default.choose()
	
	def on_create_object(self, widget, event=None):
		mi=MapItem(self,roomname())

	def parse_reality(self, reality):
		l=layout(reality)
		
		for x,y,i in l.coords():
			if i:
				m=MapItem(self,i.name)
				i.map_rep=m
				m.drag(x*100,y*100)

		for i in reality.unplaced():
			for j,k in i.exits.items():
				a=i.map_rep
				b=k.map_rep
				MapLine(a,b,j)

		self.update_scroll()


	def update_scroll(self):
		bds=list(self.canvas.root().get_bounds())
		bds[0]=min(0,bds[0])
		bds[1]=min(0,bds[1])
		bds[2]=max(self.width,bds[2])
		bds[3]=max(self.height,bds[3])
		apply(self.canvas.set_scroll_region,bds)
		# workaround for apparent bug in gnome canvas
		if bds[0] < 0 or bds[1] < 0:
			for i in self.canvas.root().children():
				i.move(0,0)
		# self.canvas.update_now()

	def unimplmented(self):
		print 'unimplemented'

	on_new= unimplmented
	on_open= unimplmented
	on_connect= unimplmented
	on_save= unimplmented

	def menubar(self):
		# 'activate' is what you would use signal_connect with
		
		_=lambda x,y,z: UIINFO_ITEM_STOCK(x,None,y,z)
		___=UIINFO_SEPARATOR
		x=lambda a,b: UIINFO_SUBTREE(a,b)
		
		return [
			x('File',[
			_('_New...',self.on_new,STOCK_MENU_NEW),
			_('_Open...',self.on_open,STOCK_MENU_OPEN),
			_('_Save',self.on_save,STOCK_MENU_SAVE),
			_('Save As...',self.on_save,STOCK_MENU_SAVE_AS),
			___,
			_('Connec_t...',self.on_connect,STOCK_MENU_REFRESH),
			___,
			_('_Quit',mainquit,STOCK_MENU_QUIT)
			])
		]
		
			
	def gtkmain(self):
		win = GnomeApp('map_editor','Twisted Plumber!')
		win.connect('delete_event', mainquit)
		win.set_title('Twisted Plumber!')

		# Create buttons.
		grid = GtkTable(3,2)

		grid.attach(self.maketool(SelectTool(self)),
					0,1,0,1)
		grid.attach(self.maketool(ExitTool(self)),
					1,2,0,1)
		grid.attach(self.maketool(PlaceTool(self)),
					2,3,0,1)
		
		grid.attach(self.maketool(SourceTool(self)),
					0,1,1,2)
		grid.attach(self.maketool(EnterTool(self)),
					1,2,1,2)
		grid.attach(self.maketool(LeaveTool(self)),
					2,3,1,2)

		fram=GtkFrame("Properties")
		#fram.set_shadow_type()
		
		v=GtkVBox()
		v.pack_start(grid,expand=FALSE)
		v.pack_start(fram,expand=TRUE)
		
		hbox = GtkHBox()
		
		hbox.pack_start(v, expand=FALSE)

		self.grid=GtkTable()

		self.canvas = GnomeCanvas()
		self.canvas.set_scroll_region(0,0, self.width, self.height)
		self.scrl = GtkScrolledWindow()
		self.scrl.add(self.canvas)

		hbox.pack_start(self.scrl, expand=TRUE)

		win.create_menus(self.menubar())
		win.set_contents(hbox)
		self.default_tool()
		win.show_all()

	def button(self,title,handler):
		w=GtkButton(title)
		w.connect('clicked',handler)
		return w

	def maketool(self,tool):
		w=GtkToggleButton(tool.name)
		tool.widget=w
		w.connect('clicked',tool.choose)
		return w
				 
	def gtk_tool_button(self,title,tool,container):
		w=GtkToggleButton(title)
		tool.widget=w
		w.connect('clicked',tool.choose)
		container.pack_start(w)
	
	def gtk_button(self,title,signal,container):
		b=GtkButton(title)
		b.connect('clicked',signal)
		container.pack_start(b)

if __name__ == '__main__':
	me = MapEditor()
	me.gtkmain()
	r=Reality()
	a=Thing("A", reality=r)
	b=Thing("B", reality=r)
	c=Thing("C", reality=r)
	d=Thing("D", reality=r)

	a.add_exit('north',b)
	b.add_exit('south',a)
	c.add_exit('east',a)
	a.add_exit('west',c)
	d.add_exit('northwest',c)
	c.add_exit('southeast',d)
	
	# me.parse_reality(r)
	from twisted.reality import default_reality
	import rpl
	me.parse_reality(default_reality)
	mainloop()