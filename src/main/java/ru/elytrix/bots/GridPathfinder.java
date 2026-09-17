package ru.elytrix.bots;

import org.bukkit.World;
import org.bukkit.block.Block;
import org.bukkit.util.BoundingBox;
import org.by1337.blib.geom.Vec3d;

import java.util.*;

/** Bounded A* over walkable block surfaces. Runs once per destination, never every tick. */
final class GridPathfinder {
    static List<Vec3d> find(World world, Vec3d start, Vec3d goal) {
        int sx=floor(start.x), sz=floor(start.z), gx=floor(goal.x), gz=floor(goal.z);
        // На открытой местности идём точной прямой под любым углом, без клеточного зигзага A*.
        if(lineClear(world,start,goal))return new ArrayList<>(List.of(goal));
        Node first=new Node(sx,sz,start.y,0,0,null);
        PriorityQueue<Node> open=new PriorityQueue<>(Comparator.comparingDouble(n->n.f));
        Map<Long,Double> best=new HashMap<>(); open.add(first); best.put(key(sx,sz),0D);
        Node closest=first; int checked=0;
        int[][] dirs={{1,0},{-1,0},{0,1},{0,-1},{1,1},{1,-1},{-1,1},{-1,-1}};
        // Жёсткий бюджет не позволяет нескольким живым ботам заморозить основной поток Paper.
        while(!open.isEmpty()&&checked++<350){
            Node n=open.poll(); if(dist(n.x,n.z,gx,gz)<dist(closest.x,closest.z,gx,gz))closest=n;
            if(n.x==gx&&n.z==gz){closest=n;break;}
            for(int[] d:dirs){int x=n.x+d[0],z=n.z+d[1];
                if(d[0]!=0&&d[1]!=0){double sideX=surface(world,x,n.z,n.y),sideZ=surface(world,n.x,z,n.y);if(Double.isNaN(sideX)||Double.isNaN(sideZ)||Math.abs(sideX-n.y)>1.01||Math.abs(sideZ-n.y)>1.01||!clear(world,x,n.z,sideX)||!clear(world,n.x,z,sideZ))continue;}
                double y=surface(world,x,z,n.y);if(Double.isNaN(y))continue;
                double delta=y-n.y;if(delta>1.01||delta<-3.5||!clear(world,x,z,y)||hazard(world,x,z,y))continue;
                double cost=n.g+(d[0]!=0&&d[1]!=0?1.414:1)+(delta>0?delta*.4:0);long key=key(x,z);
                if(cost>=best.getOrDefault(key,Double.MAX_VALUE))continue;best.put(key,cost);
                open.add(new Node(x,z,y,cost,cost+dist(x,z,gx,gz),n));
            }
        }
        LinkedList<Vec3d> path=new LinkedList<>();for(Node n=closest;n!=null;n=n.parent)path.addFirst(new Vec3d(n.x+.5,n.y,n.z+.5));
        if(path.size()>1)path.removeFirst();return simplify(world,path);
    }
    private static List<Vec3d> simplify(World world,List<Vec3d> path){
        if(path.size()<3)return path;List<Vec3d> out=new ArrayList<>();int from=0;out.add(path.get(0));
        while(from<path.size()-1){int best=from+1;for(int to=path.size()-1;to>from+1;to--)if(lineClear(world,path.get(from),path.get(to))){best=to;break;}out.add(path.get(best));from=best;}return out;
    }
    private static boolean lineClear(World world,Vec3d a,Vec3d b){double distance=Math.hypot(b.x-a.x,b.z-a.z);int steps=Math.max(1,(int)Math.ceil(distance/.25));double previous=a.y;
        for(int i=1;i<=steps;i++){double t=i/(double)steps,x=a.x+(b.x-a.x)*t,z=a.z+(b.z-a.z)*t,y=surface(world,floor(x),floor(z),previous);if(Double.isNaN(y)||y-previous>1.01||previous-y>3.5||!clearAt(world,x,z,y))return false;previous=y;}return true;}
    private static boolean clearAt(World w,double x,double z,double y){BoundingBox body=new BoundingBox(x-.29,y+.001,z-.29,x+.29,y+1.79,z+.29);for(int bx=floor(x-.29);bx<=floor(x+.29);bx++)for(int bz=floor(z-.29);bz<=floor(z+.29);bz++)for(int by=floor(y);by<=floor(y+1.79);by++){Block block=w.getBlockAt(bx,by,bz);if(!block.isPassable()&&block.getBoundingBox().overlaps(body))return false;}return true;}
    private static double surface(World w,int x,int z,double around){
        for(int by=(int)Math.floor(around)+1;by>=(int)Math.floor(around)-5;by--){Block b=w.getBlockAt(x,by,z);if(b.isPassable())continue;
            double top=b.getBoundingBox().getMaxY();if(top<=1.5)top+=by;return top;}
        return Double.NaN;
    }
    private static boolean clear(World w,int x,int z,double y){int feet=(int)Math.ceil(y);double[] o={.21,.79};for(double ox:o)for(double oz:o){int bx=(int)Math.floor(x+ox),bz=(int)Math.floor(z+oz);if(!w.getBlockAt(bx,feet,bz).isPassable()||!w.getBlockAt(bx,feet+1,bz).isPassable())return false;}return true;}
    private static boolean hazard(World w,int x,int z,double y){String m=w.getBlockAt(x,(int)Math.floor(y-.01),z).getType().name();return m.contains("LAVA")||m.contains("WATER")||m.contains("FIRE")||m.contains("CACTUS")||m.contains("MAGMA");}
    private static int floor(double v){return(int)Math.floor(v);}private static long key(int x,int z){return((long)x<<32)^(z&0xffffffffL);}private static double dist(int x,int z,int gx,int gz){return Math.hypot(gx-x,gz-z);}
    private record Node(int x,int z,double y,double g,double f,Node parent){}
}
