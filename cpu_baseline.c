/* Single-core CPU baseline for the SKI GA candidate-evaluation workload.
 * Mirrors the FPGA engine exactly: same ascending-pointer pure-SKI random
 * generation, same re-unwind WHNF reducer (3-deep window, in-place rewrite,
 * MAX_STEPS cap), same Church-boolean truth-table evaluation against XOR.
 * Measures candidates evaluated per second, single thread. */
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

enum { APP=0, S=1, K=2, I=3, T=4, F=5 };
#define PREAMBLE 5
#define MAXN 1024
#define CAND_SIZE 16
#define N_INPUTS 2
#define MAX_STEPS 2000

typedef struct { int tag, left, right; } Node;

static uint32_t lfsr = 0x12345678u;
static inline uint32_t rnd(void){
    lfsr = (lfsr >> 1) ^ (-(int32_t)(lfsr & 1u) & 0x80200003u);
    return lfsr;
}

/* Build preamble + random candidate into tmpl[]; return root, set *count. */
static int gen(Node *tmpl, int *count){
    tmpl[0]=(Node){I,0,0}; tmpl[1]=(Node){K,0,0};
    tmpl[2]=(Node){APP,1,0}; tmpl[3]=(Node){T,0,0}; tmpl[4]=(Node){F,0,0};
    for(int i=PREAMBLE;i<PREAMBLE+CAND_SIZE;i++){
        uint32_t r=rnd();
        if(i==PREAMBLE || ((r>>5)&7)<3){
            int sel=(r>>8)&3; int tag = sel==0?S : sel==1?K : I;
            tmpl[i]=(Node){tag,0,0};
        } else {
            int span=i-PREAMBLE;
            int l=PREAMBLE + (int)((((r>>10)&0xFF)*(uint32_t)span)>>8);
            int rr=PREAMBLE + (int)((((r>>18)&0xFF)*(uint32_t)span)>>8);
            tmpl[i]=(Node){APP,l,rr};
        }
    }
    *count=PREAMBLE+CAND_SIZE;
    return PREAMBLE+CAND_SIZE-1;
}

/* Re-unwind WHNF reducer (same algorithm as the FPGA FSM). Returns head tag. */
static int reduce(Node *h, int root, int count){
    int alloc=count, steps=0;
    for(;;){
        int cur=root, depth=0, a1=0,a2=0,a3=0, g1=0,g2=0,g3=0;
        while(h[cur].tag==APP){
            a3=a2; a2=a1; a1=cur;
            g3=g2; g2=g1; g1=h[cur].right;
            if(depth<3) depth++;
            cur=h[cur].left;
        }
        int ht=h[cur].tag;
        if(steps>=MAX_STEPS) return ht;
        if(ht==I && depth>=1){ h[a1]=h[g1]; steps++; continue; }
        if(ht==K && depth>=2){ h[a2]=h[g1]; steps++; continue; }
        if(ht==S && depth>=3){
            if(alloc+2>MAXN) return ht;
            h[alloc]=(Node){APP,g1,g3};
            h[alloc+1]=(Node){APP,g2,g3};
            h[a3]=(Node){APP,alloc,alloc+1};
            alloc+=2; steps++; continue;
        }
        return ht;  /* WHNF */
    }
}

/* Fitness of one candidate against the XOR truth table. */
static int fitness(Node *tmpl, int count, int root, const int *target){
    Node work[MAXN];
    int matched=0;
    for(int row=0; row<(1<<N_INPUTS); row++){
        memcpy(work, tmpl, sizeof(Node)*count);
        int acc=root, wp=count;
        for(int k=0;k<N_INPUTS+2;k++){
            int arg;
            if(k<N_INPUTS){ int bit=(row>>(N_INPUTS-1-k))&1; arg = bit?1:2; }
            else if(k==N_INPUTS) arg=3; else arg=4;
            work[wp]=(Node){APP,acc,arg}; acc=wp; wp++;
        }
        int ht=reduce(work, acc, wp);
        int got = ht==T?1 : ht==F?0 : -1;
        if(got==target[row]) matched++;
    }
    return matched;
}

int main(int argc, char**argv){
    double secs = argc>1 ? atof(argv[1]) : 3.0;
    int target[4]={0,1,1,0};  /* XOR, MSB-first rows */
    Node tmpl[MAXN];
    long n=0; int best=0;
    struct timespec t0,t1; clock_gettime(CLOCK_MONOTONIC,&t0);
    double el=0;
    do{
        for(int b=0;b<4096;b++){
            int count, root=gen(tmpl,&count);
            int fit=fitness(tmpl,count,root,target);
            if(fit>best) best=fit;
            n++;
        }
        clock_gettime(CLOCK_MONOTONIC,&t1);
        el=(t1.tv_sec-t0.tv_sec)+(t1.tv_nsec-t0.tv_nsec)/1e9;
    } while(el<secs);
    printf("CPU single-core: %.0f candidates/sec  (%ld in %.2fs, best=%d/4)\n",
           n/el, n, el, best);
    return 0;
}
