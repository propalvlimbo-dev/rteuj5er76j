package ac.grim.grimac.utils.anticheat.update;

import com.github.retrooper.packetevents.protocol.player.DiggingAction;
import com.github.retrooper.packetevents.protocol.world.BlockFace;
import com.github.retrooper.packetevents.util.Vector3i;

/**
 * EFC-совместимость: Grim BlockBreak.
 */
public class BlockBreak {

    public DiggingAction action;
    public Vector3i position;
    public BlockFace face;

    private Runnable efcCancel;

    public BlockBreak(DiggingAction action, Vector3i position, BlockFace face) {
        this.action = action;
        this.position = position;
        this.face = face;
    }

    public void onCancel(Runnable efcCancel) {
        this.efcCancel = efcCancel;
    }

    public void cancel() {
        if (efcCancel != null) {
            try {
                efcCancel.run();
            } catch (Throwable ignored) {
            }
        }
    }
}
