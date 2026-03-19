import bpy
import mido
from collections import deque

MIDI_PORT_NAME = 'IAC Driver Bus 1'

MIDI_PPQ = 24
STEPS_PER_BEAT = 2
TICKS_PER_STEP = MIDI_PPQ // STEPS_PER_BEAT

midi_queue = deque()
tick_counter = 0

midi_clock_port = None
midi_out = None

sequencers = {}
note_state = {}   # (ob, channel) -> bool
previous_note = {}

# Runs every time a midi message is received 

def midi_clock_callback(message):
    if message.type == 'clock':
        midi_queue.append('clock')
    elif message.type == 'cc':
        midi_queue.append('cc')
    elif message.type == 'start':
        midi_queue.append('start')
    elif message.type == 'stop':
        midi_queue.append('stop')

def collect_sequencers():
    global sequencers
    sequencers = {
        ob.name: ob
        for ob in bpy.data.objects
        if ob.get('_MIDI') is not None
    }

def update_sequencers(depsgraph):
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
            print(f'Note On: {note_value}, Velocity: {note_velocity}')
            midi_out.send(
                mido.Message(
                    'note_on',
                    channel=channel,
                    note=note_value,
                    velocity=note_velocity
                )
            )
        elif not note_on and previous_state:
            print(f'Note Off')
            midi_out.send(
                mido.Message(
                    'note_off',
                    channel=channel,
                    note=note_value
                )
            )
        elif note_on and previous_state:
            if note_value != prev_note:
                print(f'Note On: {note_value}, Velocity: {note_velocity}')
                midi_out.send(
                    mido.Message(
                        'note_off',
                        channel=channel,
                        note=prev_note
                    )
                )
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

        if msg == 'clock':
            clocks += 1
        elif msg == 'start':
            reset_transport()
        elif msg == 'stop':
            reset_transport()
            pass

    # Advance once per recieved clock
    for _ in range(clocks):
        advance_one_tick()

    return 0.0

# Operators

class StartMidiSync(bpy.types.Operator):
    """Start MIDI Sync"""
    bl_idname = "scene.start_midi_sync"
    bl_label = "Start MIDI Sync"

    def execute(self, context):
        global midi_clock_port, midi_out

        collect_sequencers()

        midi_clock_port = mido.open_input(MIDI_PORT_NAME)
        midi_clock_port.callback = midi_clock_callback

        midi_out = mido.open_output(MIDI_PORT_NAME)

        bpy.app.timers.register(process_midi_queue)

        print("MIDI sync started")

        return {'FINISHED'}

class StopMidiSync(bpy.types.Operator):
    """Stop MIDI Sync"""
    bl_idname = "scene.stop_midi_sync"
    bl_label = "Stop MIDI Sync"

    def execute(self, context):
        global midi_clock_port, midi_out

        if midi_clock_port:
            midi_clock_port.close()
            midi_clock_port = None

        if midi_out:
            midi_out.reset()
            midi_out.close()
            midi_out = None

        print("MIDI sync stopped")

        return {'FINISHED'}


def register():
    bpy.utils.register_class(StartMidiSync)
    bpy.utils.register_class(StopMidiSync)

def unregister():
    bpy.utils.unregister_class(StartMidiSync)
    bpy.utils.unregister_class(StopMidiSync)

if __name__ == "__main__":
    register()
