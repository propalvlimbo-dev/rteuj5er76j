package ru.elytrix.bots;

import org.bukkit.Location;
import org.bukkit.configuration.file.YamlConfiguration;
import org.bukkit.entity.Player;
import org.bukkit.plugin.java.JavaPlugin;

import java.io.File;
import java.io.IOException;
import java.util.*;

final class DatasetManager {
    private final JavaPlugin plugin;
    private final File directory;
    private final Map<UUID, Recording> recordings = new HashMap<>();
    private final List<MotionSample> samples = new ArrayList<>();
    private final List<List<MotionSample>> sequences = new ArrayList<>();

    DatasetManager(JavaPlugin plugin) {
        this.plugin = plugin;
        directory = new File(plugin.getDataFolder(), "datasets");
        if (!directory.exists()) directory.mkdirs();
        reload();
    }

    void reload() {
        samples.clear(); sequences.clear();
        File[] files = directory.listFiles((dir, name) -> name.endsWith(".yml"));
        if (files == null) return;
        for (File file : files) {
            YamlConfiguration yml = YamlConfiguration.loadConfiguration(file);
            List<MotionSample> sequence=new ArrayList<>();
            for (Map<?, ?> raw : yml.getMapList("samples")) sequence.add(MotionSample.from(raw));
            if (!sequence.isEmpty()) { sequences.add(sequence); samples.addAll(sequence); }
        }
        plugin.getLogger().info("Loaded " + samples.size() + " movement samples from datasets.");
    }

    boolean start(Player player, String name) {
        if (!name.matches("[a-zA-Z0-9_-]{1,32}") || recordings.containsKey(player.getUniqueId())) return false;
        recordings.put(player.getUniqueId(), new Recording(name, player.getLocation()));
        return true;
    }

    String stop(Player player) {
        Recording recording = recordings.remove(player.getUniqueId());
        if (recording == null) return null;
        File file = new File(directory, recording.name + ".yml");
        YamlConfiguration yml = new YamlConfiguration();
        List<Map<String, Object>> data = new ArrayList<>();
        recording.frames.forEach(frame -> data.add(frame.serialize()));
        yml.set("world", recording.world);
        yml.set("samples", data);
        try { yml.save(file); } catch (IOException ex) { plugin.getLogger().severe("Dataset save failed: " + ex.getMessage()); }
        // Новый dataset применяется только после полноценного перезапуска плагина/сервера.
        return recording.name + " (" + recording.frames.size() + " samples)";
    }

    void tick() {
        Iterator<Map.Entry<UUID, Recording>> iterator = recordings.entrySet().iterator();
        while (iterator.hasNext()) {
            Map.Entry<UUID, Recording> entry = iterator.next();
            Player player = plugin.getServer().getPlayer(entry.getKey());
            if (player == null) { iterator.remove(); continue; }
            entry.getValue().capture(player);
        }
    }

    boolean hasSamples() { return !sequences.isEmpty(); }

    List<MotionSample> randomSequence(Random random) {
        if (sequences.isEmpty()) return Collections.emptyList();
        return new ArrayList<>(sequences.get(random.nextInt(sequences.size())));
    }

    MotionSample imitate(boolean obstacle, Random random) {
        if (samples.isEmpty()) return null;
        List<MotionSample> matching = new ArrayList<>();
        for (MotionSample sample : samples) if (sample.obstacle == obstacle && sample.horizontal > 0.005) matching.add(sample);
        return matching.isEmpty() ? samples.get(random.nextInt(samples.size())) : matching.get(random.nextInt(matching.size()));
    }

    MotionSample imitateIdle(Random random) {
        if (samples.isEmpty()) return null;
        List<MotionSample> idle=new ArrayList<>();
        for (MotionSample sample:samples) if(sample.horizontal<0.015) idle.add(sample);
        return idle.isEmpty()?samples.get(random.nextInt(samples.size())):idle.get(random.nextInt(idle.size()));
    }

    double learnedJumpVelocity(double sampleSeconds) {
        double max=0;
        for(MotionSample sample:samples) if(sample.vertical>max) max=sample.vertical;
        return Math.max(7.0,Math.min(10.0,max/Math.max(.05,sampleSeconds)));
    }

    float learnedTurnSpeed() {
        List<Float> turns=new ArrayList<>();
        for(MotionSample sample:samples) if(Math.abs(sample.yawDelta)>.05F) turns.add(Math.abs(sample.yawDelta));
        if(turns.isEmpty()) return 4F;
        turns.sort(Float::compare);
        return Math.max(2F,Math.min(15F,turns.get((int)((turns.size()-1)*.85))));
    }

    int size() { return samples.size(); }

    private static final class Recording {
        final String name, world;
        final List<MotionSample> frames = new ArrayList<>();
        Location previous;
        Recording(String name, Location start) { this.name=name; this.world=start.getWorld().getName(); this.previous=start.clone(); }
        void capture(Player player) {
            Location now=player.getLocation();
            if (!now.getWorld().equals(previous.getWorld())) { previous=now.clone(); return; }
            double dx=now.getX()-previous.getX(), dy=now.getY()-previous.getY(), dz=now.getZ()-previous.getZ();
            double horizontal=Math.sqrt(dx*dx+dz*dz);
            boolean obstacle=false;
            if(horizontal>.005) {
                int x=(int)Math.floor(now.getX()+dx/horizontal*.45), y=(int)Math.floor(now.getY()), z=(int)Math.floor(now.getZ()+dz/horizontal*.45);
                obstacle=!now.getWorld().getBlockAt(x,y,z).isPassable();
            }
            frames.add(new MotionSample(horizontal,dy,wrap(now.getYaw()-previous.getYaw()),wrap(now.getPitch()-previous.getPitch()),player.isSprinting(),player.isSneaking(),player.isOnGround(),obstacle));
            previous=now.clone();
        }
    }

    static final class MotionSample {
        final double horizontal, vertical; final float yawDelta, pitchDelta; final boolean sprint, sneak, onGround, obstacle;
        MotionSample(double h,double v,float yaw,float pitch,boolean sprint,boolean sneak,boolean ground,boolean obstacle){horizontal=h;vertical=v;yawDelta=yaw;pitchDelta=pitch;this.sprint=sprint;this.sneak=sneak;onGround=ground;this.obstacle=obstacle;}
        Map<String,Object> serialize(){ Map<String,Object> m=new LinkedHashMap<>();m.put("move",horizontal);m.put("vertical",vertical);m.put("turn",yawDelta);m.put("look",pitchDelta);m.put("sprint",sprint);m.put("sneak",sneak);m.put("ground",onGround);m.put("obstacle",obstacle);return m; }
        static MotionSample from(Map<?,?> m){return new MotionSample(num(m.get("move")),num(m.get("vertical")),(float)num(m.get("turn")),(float)num(m.get("look")),bool(m.get("sprint")),bool(m.get("sneak")),bool(m.get("ground")),bool(m.get("obstacle")));}
        private static double num(Object o){return o instanceof Number?((Number)o).doubleValue():0;}
        private static boolean bool(Object o){return o instanceof Boolean&&(Boolean)o;}
    }
    private static float wrap(float yaw){while(yaw>180)yaw-=360;while(yaw<-180)yaw+=360;return yaw;}
}
