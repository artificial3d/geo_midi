import bpy
import mido
from collections import deque

MIDI_PORT_NAME = 'IAC Driver Bus 1'
MIDI_CCPORT_NAME = 'Launch Control XL'

MIDI_PPQ = 24
STEPS_PER_BEAT = 2
TICKS_PER_STEP = MIDI_PPQ // STEPS_PER_BEAT

midi_queue = deque()
cc_queue = deque()
tick_counter = 0

midi_cc_port = None
midi_clock_port = None
midi_out = None

sequencers = {}
note_state = {}   # (ob, channel) -> bool
previous_note = {}

# Runs every time a midi message is received 

def midi_clock_callback(message):
    midi_queue.append(message)

def midi_cc_callback(message):
    cc_queue.append(message)

def collect_sequencers():
    global sequencers
    sequencers = {
        ob.name: ob
        for ob in bpy.data.objects
        if ob.get('_MIDI') is not None
    }

def update_sequencers(depsgraph):
    global midi_clock_port, midi_out

    if not midi_out or not midi_clock_port:
        return

    for ob in sequencers.values():
        ob_eval = ob.evaluated_get(depsgraph)
        attrs = ob_eval.data.attributes

        if 'note_on' not in attrs:
            #print('skipping')
            continue

        note_on = bool(attrs['note_on'].data[0].value)
        note_value = int(attrs['note_value'].data[0].value)
        note_velocity = int(attrs['note_velocity'].data[0].value)

        channel = ob.get('_MIDI')

        key = (ob, channel)
        previous_state = note_state.get(key, False)
        prev_note = previous_note.get(key, False)

        #print(f'Key: {key}, Previous: {previous_state}')

        if note_on and not previous_state:
            #print(f'Note On: {note_value}, Velocity: {note_velocity}')
            midi_out.send(
                mido.Message(
                    'note_on',
                    channel=channel,
                    note=note_value,
                    velocity=note_velocity
                )
            )
        elif not note_on and previous_state:
            #print(f'Note Off')
            midi_out.send(
                mido.Message(
                    'note_off',
                    channel=channel,
                    note=note_value
                )
            )
        elif note_on and previous_state:
            if note_value != prev_note:
                #print(f'Note Off')
                midi_out.send(
                    mido.Message(
                        'note_off',
                        channel=channel,
                        note=prev_note
                    )
                )
                #print(f'Note On: {note_value}, Velocity: {note_velocity}')
                midi_out.send(
                    mido.Message(
                        'note_on',
                        channel=channel,
                        note=note_value,
                        velocity=note_velocity
                    )
            )

        note_state[key] = note_on
        previous_note[key] = note_value

def advance_one_tick():
    global tick_counter

    tick_counter += 1
    
    if tick_counter >= 2_147_483_647:
        tick_counter = 0

    timer = bpy.data.objects.get('TIMER')
    if timer:
        timer.location.x = tick_counter

    depsgraph = bpy.context.evaluated_depsgraph_get()
    update_sequencers(depsgraph)

def update_cc_objects(control, value):
    #print(f"recieved CC: {control}, {value}")
    cc_ob = bpy.data.collections['CC'].objects
    if cc_ob:
        cc_ob[control].location.y = 1/127 * value

def reset_cc_objects():
    cc_ob = bpy.data.collections['CC'].objects
    if cc_ob:
        for ob in cc_ob:
            ob.location.y = 0

def reset_transport():
    global tick_counter
    tick_counter = 0
    
    midi_out.reset()

    timer = bpy.data.objects.get('TIMER')
    if timer:
        timer.location.x = 0

def process_midi_queue():
    clocks = 0

    while midi_queue:
        msg = midi_queue.popleft()
        if msg.type == 'clock':
            clocks += 1
        elif msg.type == 'start':
            reset_transport()
        elif msg.type == 'stop':
            reset_transport()
            pass

    while cc_queue:
        msg = cc_queue.popleft()
        if msg.type == 'control_change':
            update_cc_objects(msg.control, msg.value)

    # Advance once per recieved clock
    for _ in range(clocks):
        advance_one_tick()

    return 0.0

# Interface

class MidiPanel(bpy.types.Panel):
    """Creates MIDI Panel in the Object properties window"""
    bl_label = "Midi Panel"
    bl_idname = "OBJECT_PT_midi"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Midi"

    def draw(self, context):
        global midi_clock_port, midi_out, midi_cc_port

        layout = self.layout

        row = layout.row()
        if midi_clock_port or midi_out:
            row.operator("scene.stop_midi_sync", icon='CANCEL', text='Stop MIDI')
            row = layout.row()
            row.operator("scene.midi_panic", icon='WARNING_LARGE', text='Panic')
        else:
            row.operator("scene.start_midi_sync", icon='PLAY', text='Start MIDI')

# Operators

class StartMidiSync(bpy.types.Operator):
    """Start MIDI Sync"""
    bl_idname = "scene.start_midi_sync"
    bl_label = "Start MIDI Sync"

    def execute(self, context):
        global midi_clock_port, midi_out, midi_cc_port

        collect_sequencers()

        midi_clock_port = mido.open_input(MIDI_PORT_NAME)
        midi_clock_port.callback = midi_clock_callback

        midi_out = mido.open_output(MIDI_PORT_NAME)

        midi_cc_port = mido.open_input(MIDI_CCPORT_NAME)
        midi_cc_port.callback = midi_cc_callback

        bpy.app.timers.register(process_midi_queue)

        print("MIDI sync started")

        return {'FINISHED'}

class StopMidiSync(bpy.types.Operator):
    """Stop MIDI Sync"""
    bl_idname = "scene.stop_midi_sync"
    bl_label = "Stop MIDI Sync"

    def execute(self, context):
        global midi_clock_port, midi_out, midi_cc_port

        if midi_clock_port:
            midi_clock_port.close()
            midi_clock_port = None

        if midi_out:
            reset_transport()
            midi_out.close()
            midi_out = None

        if midi_cc_port:
            reset_cc_objects()
            midi_cc_port.close()
            midi_cc_port = None

        print("MIDI sync stopped")

        return {'FINISHED'}
    
class MidiPanic(bpy.types.Operator):
    """Send Midi Panic Signal when notes get stuck"""
    bl_idname = "scene.midi_panic"
    bl_label = "MIDI Panic"

    def execute(self, context):
        global midi_out

        if midi_out:
            midi_out.panic()

        print("MIDI Panic")

        return {'FINISHED'}

classes = {
    StartMidiSync,
    StopMidiSync,
    MidiPanel,
    MidiPanic
}

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

def unregister():
    for cls in classes:
        bpy.utils.unregister_class(cls)

if __name__ == "__main__":
    register()
